#!/usr/bin/python

"""
    BurnScan ticket barcode scanner
    Copyright (C) 2010 Ben Sarsgard

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys
import time
import argparse
import re
import sqlite3
import json
import wx
import wx.adv
import pygame
import pycurl
import certifi
import nacl.utils
import base64
import os.path

# configparser changed its name in python 3
try:
    import ConfigParser as configparser
except ImportError:
    import configparser

from datetime import datetime
from xml.dom.minidom import Node
from nacl.public import Box, PrivateKey, PublicKey
from StringIO import StringIO
from urllib import urlencode

CFG_PATH = 'BurnScan.cfg'

CFG_SECTION_GENERAL = 'General'
CFG_SOUND_ACCEPT = 'sound_accept'
CFG_SOUND_REJECT = 'sound_reject'
CFG_SOUND_ERROR = 'sound_error'

CFG_SECTION_SECURITY = 'Security'
CFG_CLIENT_IDENT = 'client_ident'
CFG_CLIENT_PRIVATE_KEY = 'client_private_key'
CFG_SERVER_PUBLIC_KEY = 'server_public_key'

CFG_SECTION_DATA = 'Data'
CFG_DATABASE_PATH = 'database_path'
CFG_API_PATH = 'api_path'

STATUS_NONE = 0
STATUS_ACCEPT = 1
STATUS_REJECT = 2
STATUS_ERROR = 3

DEFAULT_STATUS = 'Ready to scan!'

class MainWindow(wx.Frame):
    def __init__(self, parent, id, title):
        wx.Frame.__init__(self, parent, id, title)
        #self.panel = wx.Panel(self)
        #self.panel.Bind(wx.EVT_KEY_UP, self.on_key_up)

        self.args = argparser.parse_args()
        self.load_config()

        try:
            self.ticket_db = sqlite3.connect(self.config.get(CFG_SECTION_DATA, CFG_DATABASE_PATH))
        except Exception as err:
            print("Error loading database: {0}".format(err))
            sys.exit()

        self.ticket_db.row_factory = sqlite3.Row

        # handle arguments
        if self.args.flush_tickets:
            self.flush_tickets()
        if self.args.flush_wristbands:
            self.flush_wristbands()
        if self.args.flush_all:
            self.flush_all()

        # configure encryption keys
        self.client_ident = self.config.get(CFG_SECTION_SECURITY, CFG_CLIENT_IDENT)
        self.client_private_key = PrivateKey(self.config.get(CFG_SECTION_SECURITY, CFG_CLIENT_PRIVATE_KEY), encoder=nacl.encoding.Base64Encoder)
        self.server_public_key = PublicKey(self.config.get(CFG_SECTION_SECURITY, CFG_SERVER_PUBLIC_KEY), encoder=nacl.encoding.Base64Encoder)

        # configure sounds
        self.sound_accept = self.config.get(CFG_SECTION_GENERAL, CFG_SOUND_ACCEPT)
        self.sound_reject = self.config.get(CFG_SECTION_GENERAL, CFG_SOUND_REJECT)
        self.sound_error = self.config.get(CFG_SECTION_GENERAL, CFG_SOUND_ERROR)

        # configure api path
        self.api_path = self.config.get(CFG_SECTION_DATA, CFG_API_PATH)

        # set api timer
        self.api_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_api, self.api_timer)
        self.api_timer.Start(1000 * 60 * 5)

        # set field timer
        self.field_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_field, self.field_timer)
        self.field_timer.Start(1000)
        self.status_check = 0

        # create fonts
        self.font_med = wx.Font(18, wx.SWISS, wx.NORMAL, wx.NORMAL, False, u'Sans Serif')
        self.font_big = wx.Font(40, wx.SWISS, wx.NORMAL, wx.NORMAL, False, u'Sans Serif')
        self.SetFont(self.font_med)

        # create the form elements
        self.textctrl_code = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        self.textctrl_code.SetEditable(True)
        self.textctrl_code.SetFont(self.font_big)
        self.button_codego = wx.Button(self, wx.ID_ANY, "Go")

        self.textctrl_result = wx.TextCtrl(self, wx.ID_ANY, DEFAULT_STATUS)
        self.textctrl_result.SetEditable(False)
        self.textctrl_result.SetFont(self.font_med)
        self.textctrl_result.SetBackgroundColour(wx.WHITE)

        self.statictext_soldlabel = wx.StaticText(self, wx.ID_ANY, "Tix Sold: ")
        self.statictext_soldvalue = wx.StaticText(self, wx.ID_ANY, "0")
        self.statictext_usedlabel = wx.StaticText(self, wx.ID_ANY, "Tix Used: ")
        self.statictext_usedvalue = wx.StaticText(self, wx.ID_ANY, "0")

        self.listctrl_searchresults = wx.ListCtrl(self, wx.ID_ANY, style=wx.LC_HRULES | wx.LC_REPORT | wx.LC_SINGLE_SEL)

        self.button_0 = wx.Button(self, wx.ID_ANY, "&0")
        self.button_1 = wx.Button(self, wx.ID_ANY, "&1")
        self.button_2 = wx.Button(self, wx.ID_ANY, "&2")
        self.button_3 = wx.Button(self, wx.ID_ANY, "&3")
        self.button_4 = wx.Button(self, wx.ID_ANY, "&4")
        self.button_5 = wx.Button(self, wx.ID_ANY, "&5")
        self.button_6 = wx.Button(self, wx.ID_ANY, "&6")
        self.button_7 = wx.Button(self, wx.ID_ANY, "&7")
        self.button_8 = wx.Button(self, wx.ID_ANY, "&8")
        self.button_9 = wx.Button(self, wx.ID_ANY, "&9")
        self.button_del = wx.Button(self, wx.ID_ANY, "&del")

        # set a statusbar
        self.CreateStatusBar(style=0)

        # create sizers and place elements
        self.sizer_code = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_code.Add(self.textctrl_code, 1, wx.EXPAND)
        self.sizer_code.Add(self.button_codego, 0, wx.EXPAND)
        
        self.sizer_panel_stats_sold = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_panel_stats_sold.Add(self.statictext_soldlabel, 2, wx.ALIGN_CENTER)
        self.sizer_panel_stats_sold.Add(self.statictext_soldvalue, 1, wx.ALIGN_CENTER)
        
        self.sizer_panel_stats_used = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_panel_stats_used.Add(self.statictext_usedlabel, 2, wx.ALIGN_CENTER)
        self.sizer_panel_stats_used.Add(self.statictext_usedvalue, 1, wx.ALIGN_CENTER)
        
        self.sizer_panel_stats = wx.BoxSizer(wx.VERTICAL)
        self.sizer_panel_stats.Add(self.sizer_panel_stats_sold, 1, wx.EXPAND)
        self.sizer_panel_stats.Add(self.sizer_panel_stats_used, 1, wx.EXPAND)

        self.sizer_panel = wx.BoxSizer(wx.VERTICAL)
        self.sizer_panel.Add(self.sizer_panel_stats, 1, wx.EXPAND)
        self.sizer_panel.Add(self.listctrl_searchresults, 7, wx.EXPAND)

        self.sizer_keypad_row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_keypad_row1.Add(self.button_7, 1, wx.EXPAND)
        self.sizer_keypad_row1.Add(self.button_8, 1, wx.EXPAND)
        self.sizer_keypad_row1.Add(self.button_9, 1, wx.EXPAND)
        
        self.sizer_keypad_row2 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_keypad_row2.Add(self.button_4, 1, wx.EXPAND)
        self.sizer_keypad_row2.Add(self.button_5, 1, wx.EXPAND)
        self.sizer_keypad_row2.Add(self.button_6, 1, wx.EXPAND)
        
        self.sizer_keypad_row3 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_keypad_row3.Add(self.button_1, 1, wx.EXPAND)
        self.sizer_keypad_row3.Add(self.button_2, 1, wx.EXPAND)
        self.sizer_keypad_row3.Add(self.button_3, 1, wx.EXPAND)
        
        self.sizer_keypad_row4 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_keypad_row4.Add(self.button_0, 2, wx.EXPAND)
        self.sizer_keypad_row4.Add(self.button_del, 1, wx.EXPAND)
        
        self.sizer_keypad = wx.BoxSizer(wx.VERTICAL)
        self.sizer_keypad.Add(self.sizer_keypad_row1, 1, wx.EXPAND)
        self.sizer_keypad.Add(self.sizer_keypad_row2, 1, wx.EXPAND)
        self.sizer_keypad.Add(self.sizer_keypad_row3, 1, wx.EXPAND)
        self.sizer_keypad.Add(self.sizer_keypad_row4, 1, wx.EXPAND)

        self.sizer_controls = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_controls.Add(self.sizer_panel, 1, wx.EXPAND)
        self.sizer_controls.Add(self.sizer_keypad, 1, wx.EXPAND)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.sizer_code, 0, wx.EXPAND)
        self.sizer.Add(self.textctrl_result, 0, wx.EXPAND)
        self.sizer.Add(self.sizer_controls, 1, wx.EXPAND)

        self.SetSizer(self.sizer)
        self.SetAutoLayout(1)
        self.sizer.Fit(self)

        # attach events
        self.Bind(wx.EVT_BUTTON, lambda e, n=0: self.on_button_num(e, n), self.button_0)
        self.Bind(wx.EVT_BUTTON, lambda e, n=1: self.on_button_num(e, n), self.button_1)
        self.Bind(wx.EVT_BUTTON, lambda e, n=2: self.on_button_num(e, n), self.button_2)
        self.Bind(wx.EVT_BUTTON, lambda e, n=3: self.on_button_num(e, n), self.button_3)
        self.Bind(wx.EVT_BUTTON, lambda e, n=4: self.on_button_num(e, n), self.button_4)
        self.Bind(wx.EVT_BUTTON, lambda e, n=5: self.on_button_num(e, n), self.button_5)
        self.Bind(wx.EVT_BUTTON, lambda e, n=6: self.on_button_num(e, n), self.button_6)
        self.Bind(wx.EVT_BUTTON, lambda e, n=7: self.on_button_num(e, n), self.button_7)
        self.Bind(wx.EVT_BUTTON, lambda e, n=8: self.on_button_num(e, n), self.button_8)
        self.Bind(wx.EVT_BUTTON, lambda e, n=9: self.on_button_num(e, n), self.button_9)
        self.Bind(wx.EVT_BUTTON, self.on_button_del, self.button_del)
        self.Bind(wx.EVT_BUTTON, self.on_button_code_go, self.button_codego)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_button_code_go, self.textctrl_code)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_listctrl_searchresults_activated, self.listctrl_searchresults)

        self.Show(True)
        # self.ShowFullScreen(True, style=wx.FULLSCREEN_ALL)
        self.reset_all()

    def load_config(self):
        self.config = configparser.RawConfigParser()
        self.config.read(CFG_PATH)

    def play_sound_accept(self):
        pygame.mixer.Sound(self.sound_accept).play()
        return True

    def play_sound_reject(self):
        pygame.mixer.Sound(self.sound_reject).play()
        return True

    def play_sound_error(self):
        pygame.mixer.Sound(self.sound_error).play()
        return True

    def on_button_num(self, e, num):
        self.textctrl_code.AppendText(str(num))
        self.textctrl_code.SetFocus()

    def on_button_del(self, e):
        self.textctrl_code.Remove(len(self.textctrl_code.GetValue()) - 1, len(self.textctrl_code.GetValue()))
        self.textctrl_code.SetFocus()

    def on_button_code_go(self, e):
        query = self.textctrl_code.GetValue()
        return self.check_entry(query)

    def on_listctrl_searchresults_activated(self, e):
        query = e.GetLabel()
        return self.check_entry(query)

    def flush_tickets(self):
        cursor = self.ticket_db.cursor()
        sql_flush = '''DELETE FROM `tickets`'''
        cursor.execute(sql_flush)
        cursor.close()
        self.ticket_db.commit()
        return True

    def flush_wristbands(self):
        cursor = self.ticket_db.cursor()
        sql_flush = '''DELETE FROM `checkins`'''
        cursor.execute(sql_flush)
        sql_counter = '''UPDATE `sqlite_sequence` SET `seq` = 0 WHERE `name` = 'checkins' LIMIT 1'''
        cursor.execute(sql_counter)
        cursor.close()
        self.ticket_db.commit()
        return True

    def flush_all(self):
        self.flush_wristbands()
        self.flush_tickets()
        return True

    def check_entry(self, query):
        if re.match('[0-9]{10}', query):
            return self.check_code(query)
        elif query == 'REFRESH':
            self.set_status(STATUS_NONE, 'Forcing database update...')
            if self.update_api(1):
                self.set_status(STATUS_ACCEPT, 'Database up to date!')
            else:
                self.set_status(STATUS_ERROR, 'Database update failed!')
            self.reset_all()
        else:
            return self.search_tickets(query)

    def wristband_entry(self):
        wristband_dialog = wx.TextEntryDialog(self,"Enter Wristband ID")
        if wristband_dialog.ShowModal() == wx.ID_OK:
            wristband_id = abs(int(wristband_dialog.GetValue()))
        else:
            return -1

        cursor = self.ticket_db.cursor()
        sql_wristband_search = '''SELECT COUNT(*) FROM `checkins` WHERE `wristband` = ? LIMIT 1'''
        cursor.execute(sql_wristband_search, (wristband_id,))
        wristband_count = cursor.fetchone()
        cursor.close()

        if int(wristband_count[0]) != 0:
            wristband_error = 'Wristband ID "%s" already entered!' % (wristband_id)
            error_dialog = wx.MessageDialog(self, wristband_error,'Error', wx.OK|wx.ICON_ERROR|wx.STAY_ON_TOP)
            error_dialog.ShowModal()
            return 0

        return wristband_id

    def search_tickets(self, searchfilter):
        self.reset_searchresults()
        self.textctrl_code.SetFocus()

        if not re.match('[0-9a-zA-Z@\.\-]+', searchfilter):
            return False

        query_string = '%%%s%%' % searchfilter
        cursor = self.ticket_db.cursor()
        sql_search = '''SELECT *
            FROM `tickets` AS `tix1`
            WHERE
                (
                    `tix1`.`purchase_email` LIKE ?
                    OR `tix1`.`purchase_name` LIKE ?
                    OR `tix1`.`assigned_email` LIKE ?
                    OR `tix1`.`waiver_name` LIKE ?
                )
                AND ((
                    `tix1`.`id` = (
                        SELECT MAX(`tix2`.`id`)
                        FROM `tickets` as `tix2`
                        WHERE
                            `tix2`.`ticket_number` = `tix1`.`ticket_number`
                            AND `tix2`.`ticket_code` = `tix1`.`ticket_code`
                            AND `tix2`.`tier_code` = `tix1`.`tier_code`
                    )
                    AND (
                        (
                            SELECT `chex1`.`ticket_id`
                            FROM `checkins` AS `chex1`
                            WHERE
                                `chex1`.`ticket_number` = `tix1`.`ticket_number`
                                AND `chex1`.`ticket_code` = `tix1`.`ticket_code`
                                AND `chex1`.`tier_code` = `tix1`.`tier_code`
                            LIMIT 1
                        ) = `tix1`.`id`
                        OR (
                            SELECT COUNT(*)
                            FROM `checkins` AS `chex2`
                            WHERE
                                `chex2`.`ticket_number` = `tix1`.`ticket_number`
                                AND `chex2`.`ticket_code` = `tix1`.`ticket_code`
                                AND `chex2`.`tier_code` = `tix1`.`tier_code`
                        ) = 0
                    )
                )
                OR (
                    (
                        SELECT `chex3`.`ticket_id`
                        FROM `checkins` as `chex3`
                        WHERE
                            `chex3`.`ticket_number` = `tix1`.`ticket_number`
                            AND `chex3`.`ticket_code` = `tix1`.`ticket_code`
                            AND `chex3`.`tier_code` = `tix1`.`tier_code`
                        LIMIT 1
                    ) = `tix1`.`id`
                ))
            ORDER BY waiver_name'''
        cursor.execute(sql_search, (query_string, query_string, query_string, query_string))
        search_results = cursor.fetchall()
        cursor.close()
 
        t = 0
        for ticket in search_results:
            if not ticket['assigned_email']:
                ticket_email = ticket['purchase_email']
            else:
                ticket_email = ticket['assigned_email']
            ticket_number = "%i%05i%04i" % (ticket['tier_code'], ticket['ticket_number'], ticket['ticket_code'])
            ticket_name = ticket['waiver_name']
            self.listctrl_searchresults.InsertItem(t, ticket_number)
            self.listctrl_searchresults.SetItem(t, 1, ticket_name)
            self.listctrl_searchresults.SetItem(t, 2, ticket_email)
            t += 1
        
        if t == 0:
            self.set_status(STATUS_ERROR, 'Search returned 0 results!')
            return False
        
        return True

    def set_stats(self):
        tickets_sold = 0
        tickets_used = 0

        cursor = self.ticket_db.cursor()
        sql_sold = '''SELECT COUNT(*) FROM (SELECT DISTINCT `ticket_number`, `ticket_code`, `tier_code` FROM `tickets`)'''
        sql_used = '''SELECT COUNT(DISTINCT `ticket_id`) FROM `checkins`'''
        cursor.execute(sql_sold)
        res_sold = cursor.fetchone()
        tickets_sold = int(res_sold[0])
        cursor.execute(sql_used)
        res_used = cursor.fetchone()
        tickets_used = int(res_used[0])
        cursor.close()

        self.statictext_soldvalue.SetLabel(str(tickets_sold))
        self.statictext_usedvalue.SetLabel(str(tickets_used))

        return True

    def check_code(self, code):
        check_tier_code = code[0]
        check_ticket_number = code[1:6]
        check_ticket_code = code[6:10]
        
        cursor = self.ticket_db.cursor()
        sql_ticket = '''SELECT *
            FROM `tickets` AS `tix1`
            WHERE
            (
                `tix1`.`tier_code` = ?
                AND `tix1`.`ticket_number` = ?
                AND `tix1`.`ticket_code` = ?
            )
            AND ((
                    `tix1`.`id` = (
                        SELECT MAX(`tix2`.`id`)
                        FROM `tickets` as `tix2`
                        WHERE
                            `tix2`.`ticket_number` = `tix1`.`ticket_number`
                            AND `tix2`.`ticket_code` = `tix1`.`ticket_code`
                            AND `tix2`.`tier_code` = `tix1`.`tier_code`
                    )
                    AND (
                        (
                            SELECT `chex1`.`ticket_id`
                            FROM `checkins` AS `chex1`
                            WHERE
                                `chex1`.`ticket_number` = `tix1`.`ticket_number`
                                AND `chex1`.`ticket_code` = `tix1`.`ticket_code`
                                AND `chex1`.`tier_code` = `tix1`.`tier_code`
                            LIMIT 1
                        ) = `tix1`.`id`
                        OR (
                            SELECT COUNT(*)
                            FROM `checkins` AS `chex2`
                            WHERE
                                `chex2`.`ticket_number` = `tix1`.`ticket_number`
                                AND `chex2`.`ticket_code` = `tix1`.`ticket_code`
                                AND `chex2`.`tier_code` = `tix1`.`tier_code`
                        ) = 0
                    )
                )
                OR (
                    (
                        SELECT `chex3`.`ticket_id`
                        FROM `checkins` as `chex3`
                        WHERE
                            `chex3`.`ticket_number` = `tix1`.`ticket_number`
                            AND `chex3`.`ticket_code` = `tix1`.`ticket_code`
                            AND `chex3`.`tier_code` = `tix1`.`tier_code`
                        LIMIT 1
                    ) = `tix1`.`id`
                ))
            LIMIT 1'''
        cursor.execute(sql_ticket, (check_tier_code, check_ticket_number, check_ticket_code))
        ticket = cursor.fetchone()
        cursor.close()

        if ticket is None:
            self.set_status(STATUS_REJECT, 'Ticket not found!')
            self.reset_all()
            return False
        
        ticket_id = ticket['id']

        return self.check_ticket(ticket_id)
    
    def check_ticket(self, ticket_id):
        ticket_cursor = self.ticket_db.cursor()
        sql_ticket = '''SELECT `tickets`.*,
            (SELECT COUNT(*)
                FROM `checkins`
                WHERE `checkins`.`ticket_id` = `tickets`.`id`
            ) AS `wristband_count`,
            (SELECT `wristband`
                FROM `checkins`
                WHERE `checkins`.`ticket_id` = `tickets`.`id`
                ORDER BY `checkins`.`date` DESC
                LIMIT 1
            ) AS `wristband_current`
            FROM `tickets`
            WHERE `id` = ?
            LIMIT 1'''
        ticket_cursor.execute(sql_ticket, (ticket_id,))
        ticket = ticket_cursor.fetchone()
        ticket_cursor.close()

        if int(ticket['wristband_count']) > 0:
            confirm_dialog = wx.MessageDialog(self, 'Ticket already used! Are you replacing a wristband?','Warning!', wx.YES_NO|wx.NO_DEFAULT|wx.ICON_EXCLAMATION|wx.STAY_ON_TOP)
            if confirm_dialog.ShowModal() == wx.ID_NO:
                self.set_status(STATUS_REJECT, 'Ticket already used!')
                self.reset_all()
                return False

        if not ticket['assigned_email']:
            email = ticket['purchase_email']
        else:
            email = ticket['assigned_email']

        message = 'Ticket#: %i%05i%04i\n' % (ticket['tier_code'], ticket['ticket_number'], ticket['ticket_code'])
        if int(ticket['wristband_count']) > 0:
        	message += 'Current Wristband: %s\n' % (ticket['wristband_current'])
        message += 'Wristbands Used: %s\n\n' % (ticket['wristband_count'])
        message += '#### CHECK ID WITH INFORMATION BELOW ####\n\n'
        message += 'Name: %s\n' % (ticket['waiver_name'])
        message += 'State: %s\n' % (ticket['waiver_state'])
        message += 'Email: %s\n\n' % (email)
        message += '#### CHECK ID WITH INFORMATION ABOVE ####\n\n'
        message += 'Purchaser Name: %s\n' % (ticket['purchase_name'])
        message += 'Purchaser Email: %s\n\n' % (ticket['purchase_email'])
        message += '#### EMERGENCY CONTACT ####\n\n'
        message += ticket['waiver_emergency']

        confirm_dialog = wx.MessageDialog(self, message,'Confirm Selection', wx.OK|wx.CANCEL|wx.CANCEL_DEFAULT|wx.ICON_QUESTION|wx.STAY_ON_TOP)

        if confirm_dialog.ShowModal() == wx.ID_CANCEL:
            return False
        
        confirm_dialog.Destroy()

        wristband_id = 0
        while wristband_id == 0:
            wristband_id = self.wristband_entry()

        if int(wristband_id) < 1:
            return False

        checkin_cursor = self.ticket_db.cursor()
        sql_checkin = '''INSERT INTO `checkins`
            (`ticket_id`,`date`,`wristband`,`ticket_number`, `ticket_code`, `tier_code`)
            VALUES (?, ?, ?, ?, ?, ?)'''
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        checkin_cursor.execute(sql_checkin, (
            ticket_id, date, wristband_id, ticket['ticket_number'],
            ticket['ticket_code'], ticket['tier_code']))
        checkin_cursor.close()
        self.ticket_db.commit()

        self.set_status(STATUS_ACCEPT, 'Ticket accepted!')
        self.reset_all() 
        return True

    def set_status(self, type, message):
        self.textctrl_result.SetValue(message)

        if type == STATUS_ACCEPT:
            self.textctrl_result.SetBackgroundColour(wx.GREEN)
            self.play_sound_accept()
        elif type == STATUS_REJECT:
            self.textctrl_result.SetBackgroundColour(wx.RED)
            self.play_sound_reject()
        elif type == STATUS_ERROR:
            self.textctrl_result.SetBackgroundColour(wx.YELLOW)
            self.play_sound_error()
        else:
            self.textctrl_result.SetBackgroundColour(wx.WHITE)
        
        return True

    def reset_searchresults(self):
        self.listctrl_searchresults.ClearAll()
        self.listctrl_searchresults.AppendColumn("Ticket", width=150)
        self.listctrl_searchresults.AppendColumn("Name", width=250)
        self.listctrl_searchresults.AppendColumn("Email", width=250)
        return True

    def reset_all(self):
        self.reset_searchresults()
        self.textctrl_code.Clear()
        self.set_stats()
        self.textctrl_code.SetFocus()
        self.SetStatusText('')
        return True
        
    def update_field(self, e):
        if self.textctrl_result.GetValue() != DEFAULT_STATUS:
            if self.status_check < 3:
                self.status_check += 1
            else:
                self.set_status(STATUS_NONE, DEFAULT_STATUS)
                self.status_check = 0
        
        if self.textctrl_code.GetValue() == '':
            self.textctrl_code.SetFocus()
        return True

    def query_server(self, request):
        json_request = json.dumps(request)
        box_server = Box(self.client_private_key, self.server_public_key)
        bin_request = box_server.encrypt(json_request)
        io_buffer = StringIO()
        curl_query = pycurl.Curl()
        curl_query.setopt(curl_query.URL, self.api_path)
        b64_request = base64.b64encode(bin_request)
        post_data = {'i': self.client_ident, 'r': b64_request}
        post_fields = urlencode(post_data)
        curl_query.setopt(curl_query.POSTFIELDS, post_fields)
        curl_query.setopt(curl_query.WRITEDATA, io_buffer)
        curl_query.setopt(curl_query.CAINFO, certifi.where())
        try:
            curl_query.perform()
            curl_query.close()
        except pycurl.error:
            return False;
        bin_response = base64.b64decode(io_buffer.getvalue())
        json_response = box_server.decrypt(bin_response)
        obj_response = json.loads(json_response)
        return obj_response
        

    def update_api(self, e):
        last_cursor = self.ticket_db.cursor()
        sql_last = '''SELECT `id` FROM `tickets` ORDER BY `id` DESC LIMIT 1'''
        last_cursor.execute(sql_last)
        last_ticket = last_cursor.fetchone()
        last_cursor.close()
        if last_ticket is None:
            ticket_id = 0
        else:
            ticket_id = last_ticket['id']
        arr_request = {'command': 'update', 'id': ticket_id}
        api_response = self.query_server(arr_request)
        if api_response == False:
            return False
        if len(api_response) < 1:
            return True
        insert_template = '''INSERT INTO `tickets`
            (`id`, `import_id`, `ticket_number`, `ticket_code`,`tier_id`,
            `tier_code`, `tier_label`, `purchase_date`, `purchase_email`,
            `purchase_name`, `assigned_email`, `waiver_name`, `waiver_state`,
            `waiver_emergency`)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''
        update_cursor = self.ticket_db.cursor()
        for ticket in api_response:
            update_cursor.execute(insert_template,
                (ticket['id'], ticket['import_id'], ticket['ticket_number'],
                ticket['ticket_code'], ticket['tier_id'], ticket['tier_code'],
                ticket['tier_label'], ticket['purchase_date'], ticket['purchase_email'],
                ticket['purchase_name'], ticket['assigned_email'], ticket['waiver_name'],
                ticket['waiver_state'], ticket['waiver_emergency']))
        update_cursor.close()
        self.ticket_db.commit()
        self.set_stats()
        return True

argparser = argparse.ArgumentParser(description='BurnScan Ticket Station')
argparser.add_argument('--flush-tickets', action='store_true', help='Flush the ticket table.')
argparser.add_argument('--flush-wristbands', action='store_true', help='Flush the wristband table.')
argparser.add_argument('--flush-all', action='store_true', help='Flush the entire database.')

pygame.init()
app = wx.App()
frame = MainWindow(None, wx.ID_ANY, 'BurnScan')
app.MainLoop()
