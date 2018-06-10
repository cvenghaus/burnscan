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
import random
import hashlib
import argparse
import re
import sqlite3
import wx
import wx.adv
import pygame

# configparser changed its name in python 3
try:
    import ConfigParser as configparser
except ImportError:
    import configparser

from datetime import datetime
from datetime import timedelta
from xml.dom.minidom import Node

CFG_PATH = 'BurnScan.cfg'

CFG_SECTION_GENERAL = 'General'
CFG_DATABASE_PATH = 'database_path'
CFG_SOUND_ACCEPT = 'sound_accept'
CFG_SOUND_REJECT = 'sound_reject'
CFG_SOUND_ERROR = 'sound_error'

CFG_SECTION_SECURITY = 'Security'
CFG_PASSWORD_RAW = 'password_raw'
CFG_PASSWORD_ENC = 'password_enc'

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

        if self.args.cryptconfig:
            self.crypt_config()

        try:
            self.ticket_db = sqlite3.connect(self.config.get(CFG_SECTION_GENERAL, CFG_DATABASE_PATH))
        except Exception as err:
            print("Error loading database: {0}".format(err))
            sys.exit()

        self.ticket_db.row_factory = sqlite3.Row

        # configure sounds
        self.sound_accept = self.config.get(CFG_SECTION_GENERAL, CFG_SOUND_ACCEPT)
        self.sound_reject = self.config.get(CFG_SECTION_GENERAL, CFG_SOUND_REJECT)
        self.sound_error = self.config.get(CFG_SECTION_GENERAL, CFG_SOUND_ERROR)

        # set timer
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update, self.timer)
        self.timer.Start(1000)
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
        self.CreateStatusBar()

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
        #self.ShowFullScreen(True, style=wx.FULLSCREEN_ALL)
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

    def crypt_config(self):
        if self.config.has_option(CFG_SECTION_SECURITY, CFG_PASSWORD_RAW):
            password_raw = self.config.get(CFG_SECTION_SECURITY, CFG_PASSWORD_RAW)
            password_enc = hashlib.sha256(password_raw.encode()).hexdigest()
            self.config.set(CFG_SECTION_SECURITY, CFG_PASSWORD_ENC, password_enc)
            self.config.remove_option(CFG_SECTION_SECURITY, CFG_PASSWORD_RAW)
            configfile = open(CFG_PATH, 'wb')
            self.config.write(configfile)
            print("Password encrypted!")
            return True
        else:
            if self.config.has_option(CFG_SECTION_SECURITY, CFG_PASSWORD_ENC):
                print("Password already encrypted!")
                return False
            else:
                print("No password to encrypt!")
                return False

    def authenticate(self):
        authorized = False
        dialog = wx.PasswordEntryDialog(self, 'Password:', 'authenticate yourself')
        if dialog.ShowModal() == wx.ID_OK:
            answer = str(dialog.GetValue())
            if self.config.has_option(CFG_SECTION_SECURITY, CFG_PASSWORD_ENC):
                password = self.config.get(CFG_SECTION_SECURITY, CFG_PASSWORD_ENC)
                answer_hash = hashlib.sha256(answer.encode()).hexdigest()
                if answer_hash == password:
                    authorized = True
            else:
                password = self.config.get(CFG_SECTION_SECURITY, CFG_PASSWORD_RAW)
                if answer == password:
                   authorized = True
        if not authorized:
            dialog = wx.MessageDialog(self, 'Invalid Password', 'Authentication Failed')
            dialog.ShowModal()
        dialog.Destroy()
        return authorized

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

    def check_entry(self, query):
        if re.match('[0-9]{10}', query):
            return self.check_code(query)
        else:
            return self.search_tickets(query)

    def wristband_entry(self):
        wristband_dialog = wx.TextEntryDialog(self,"Enter Wristband ID")
        if wristband_dialog.ShowModal() == wx.ID_OK:
            wristband_id = abs(int(wristband_dialog.GetValue()))
        else:
            return -1

        cursor = self.ticket_db.cursor()
        sql_wristband_search = '''SELECT COUNT(*) FROM `checkins` WHERE `wristband` = '{0}' LIMIT 1'''
        cursor.execute(sql_wristband_search.format(wristband_id))
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

        cursor = self.ticket_db.cursor()
        sql_search = '''SELECT * FROM `tickets`
            WHERE `purchase_email` LIKE '%%{0}%%'
            OR `purchase_name` LIKE '%%{0}%%'
            OR `assigned_email` LIKE '%%{0}%%'
            OR `waiver_first_name` LIKE '%%{0}%%'
            OR `waiver_last_name` LIKE '%%{0}%%'
            ORDER BY waiver_last_name, waiver_first_name'''
        cursor.execute(sql_search.format(searchfilter))
        search_results = cursor.fetchall()
        cursor.close()
 
        t = 0
        for ticket in search_results:
            if not ticket['assigned_email']:
                ticket_email = ticket['purchase_email']
            else:
                ticket_email = ticket['assigned_email']
            ticket_number = "%i%05i%04i" % (ticket['tier_code'], ticket['ticket_number'], ticket['ticket_code'])
            ticket_name = "%s, %s" % (ticket['waiver_last_name'], ticket['waiver_first_name'])
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
        sql_sold = '''SELECT COUNT(*) FROM `tickets`'''
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

    def check_code(self, code):
        check_tier_code = code[0]
        check_ticket_number = code[1:6]
        check_ticket_code = code[6:10]
        
        cursor = self.ticket_db.cursor()
        sql_ticket = '''SELECT *
            FROM `tickets`
            WHERE `tier_code` = '{0}'
            AND `ticket_number` = '{1}'
            AND `ticket_code` = '{2}'
            LIMIT 1'''
        cursor.execute(sql_ticket.format(check_tier_code, check_ticket_number, check_ticket_code))
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
            WHERE `id` = '{0}'
            LIMIT 1'''
        ticket_cursor.execute(sql_ticket.format(ticket_id))
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
        message += 'Name: %s, %s\n' % (ticket['waiver_last_name'], ticket['waiver_first_name'])
        message += 'State: %s\n' % (ticket['waiver_state'])
        message += 'Email: %s\n\n' % (email)
        message += '#### CHECK ID WITH INFORMATION ABOVE ####\n\n'
        message += 'Purchaser Name: %s\n' % (ticket['purchase_name'])
        message += 'Purchaser Email: %s' % (ticket['purchase_email'])

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
        sql_checkin = '''INSERT INTO `checkins`(`ticket_id`,`date`,`wristband`) VALUES ('{0}', '{1}', '{2}')'''
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        checkin_cursor.execute(sql_checkin.format(ticket_id, date, wristband_id))
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
        return True
        
    def update(self, e):
        if self.textctrl_result.GetValue() != DEFAULT_STATUS:
            if self.status_check < 3:
                self.status_check += 1
            else:
                self.set_status(STATUS_NONE, DEFAULT_STATUS)
                self.status_check = 0
        
        if self.textctrl_code.GetValue() == '':
            self.textctrl_code.SetFocus()
        return True
        

argparser = argparse.ArgumentParser(description="BurnScan Ticket Station")
argparser.add_argument("--cryptconfig", action='store_true', help="Encrypt the admin password (if it isn't already encrypted).")

pygame.init()
app = wx.App()
frame = MainWindow(None, wx.ID_ANY, 'BurnScan')
app.MainLoop()
