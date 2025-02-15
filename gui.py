import base64
import collections
import http.client
import json
import logging
import os
import os.path
import platform
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Optional

__version__ = '2'
HOST = ''
NODE_PATH = None


# HOST = 'ribica.dev'

def rightnow():
    return datetime.now().strftime("%Y%m%d_%H%M%S.%f")


def ensure_folder(name):
    try:
        os.mkdir(name)
    except FileExistsError:
        pass


class Account:
    def __init__(self, username: str, gui_: 'MainGUI', list_type: str, list_: list[str], strict: bool, quiet: bool,
                note: str, lobby_name: str = None, lobby_number: int = None):
        self.username = username
        self.gui = gui_
        self.list_type = list_type
        self.list = list_
        self.strict = strict
        self.quiet = quiet
        self.note = note
        self.lobby_name = lobby_name if lobby_name else "main"
        self.lobby_number = lobby_number if lobby_number else 8
        self.in_party = False
        self.chat_history = collections.deque(maxlen=250)
        self.connected: bool = False
        self.process: Optional[subprocess.Popen] = None
        self.stdin_thread: Optional[threading.Thread] = None
        self.stdout_thread: Optional[threading.Thread] = None
        self.input_queue: Optional[queue.Queue] = None
        self.node_script_version: str = 'null'

    def __repr__(self):
        return f'<Account {self.username} {self.list_type} {self.list} strict={self.strict}>'

    def to_dict(self, extra=False) -> dict:
        d = {
            'username': self.username,
            'list_type': self.list_type,
            'list': deepcopy(self.list),
            'strict': self.strict,
            'quiet': self.quiet,
            'note': self.note
        }
        if extra:
            d.update({
                'in_party': self.in_party,
                'lobby_name': self.lobby_name,
                'lobby_number': self.lobby_number,
                'client_version': str(self.node_script_version),
                'client_gui_version': str(__version__)
            })
        return d

    def connect(self):
        if self.connected:
            raise RuntimeError('Attempted to connect an account that is already connected')

        # start a new thread that runs 'node main.js <account_username>' and save the thread object in self.acc_threads
        # have a callback function when the process outputs something
        def _process_output():
            acc_logger = logging.getLogger(self.username)
            acc_logger.propagate = False  # logs from this account should not go to gui logs
            h = logging.FileHandler(f'logs/{self.username}_{rightnow()}.log', mode='w', encoding='utf8')
            h.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s'))
            acc_logger.addHandler(h)
            logging.debug(f'Process "{self.username}" started')
            self.chat_history.append('')
            self.chat_history.append('=' * 27 + ' RESTART ' + '=' * 27)
            self.chat_history.append('')
            while self.process.poll() is None:
                line: str = self.process.stdout.readline().strip()
                if line.startswith('$') and len(line) >= 3:
                    data_id = int(line[1:3])
                    line = line[3:]
                    if data_id == 0:  # normal chat message
                        acc_logger.info(chat_line := base64.b64decode(line).decode())
                        self.chat_history.append(chat_line)
                        if self.gui.selected_account == self:
                            self.gui.textarea_lines.put(chat_line)
                            self.gui.root.after(0, self.gui.add_pending_textarea_lines)
                    elif data_id == 1:
                        title, name = map(lambda t: base64.b64decode(t).decode('ansi'), line.split('$'))
                        acc_logger.debug(f'{self.username} scoreboardPosition {title=} {name=}')
                    elif data_id == 2:
                        pass  # warped in party, warper = base64.b64decode(line).decode()
                    elif data_id == 3:
                        pass  # kicked from party, kicker = base64.b64decode(line).decode()
                    elif data_id == 4:
                        acc_logger.debug(f'{self.username} sending : {line}')
                    elif data_id == 98:  # update some property
                        acc_logger.debug(f'{self.username} state update: {line}')
                        setattr(self, *json.loads(line))
                        self.gui.update_remote()
                elif line.startswith('To sign in'):
                    code = line[line.find('the code ') + 9:line.find(' or visit')]
                    if messagebox.askyesno(
                            'Authentication',
                            'This is your first time connecting this account. Please go to '
                            'https://www.microsoft.com/link in your web browser (recommended in incognito/private mode) '
                            f'and enter the code {code}, then log in to the account whose username is "{self.username}". '
                            'Click "Yes" if you want to open that link in your browser now.\n\nImportant: Usernames '
                            'are just for your reference, please make sure to log in with the correct account!'
                    ):
                        webbrowser.open('https://www.microsoft.com/link')
                elif line.startswith('[msa]'):
                    logging.info(line)
                elif line:
                    logging.warning(f'> {line}')

            code = self.process.wait()
            logging.info(f'Process "{self.username}" ended with code {code}')
            self.connected = False
            self.process = None
            self.stdin_thread = None
            self.stdout_thread = None
            self.input_queue = None

        def _process_input():
            while True:
                data = self.input_queue.get()
                if data is None:
                    break
                logging.info(f'Sending to {self.username}: {data}')
                self.process.stdin.write(data + '\n')
                self.process.stdin.flush()

        def _worker():
          
            self.lobby_name, self.lobby_number = "main", 8
            self.process = subprocess.Popen(
                [NODE_PATH, 'main.js', self.username, self.lobby_name, str(self.lobby_number)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            self.input_queue = queue.Queue()
            self.stdout_thread = threading.Thread(target=_process_output, name=f'ThreadStdout-{self.username}',
                                                  daemon=True)
            self.stdout_thread.start()
            self.stdin_thread = threading.Thread(target=_process_input, name=f'ThreadStdin-{self.username}',
                                                 daemon=True)
            self.stdin_thread.start()
            self.connected = True
            self.send_whitelist_update()
            self.gui.root.after(0, self.gui.update)

        t = threading.Thread(target=_worker, name=f'ThreadConnect-{self.username}', daemon=True)
        t.start()

    def disconnect(self):
        if not self.connected:
            raise RuntimeError('Attempted to disconnect an account that is not connected')
        logging.debug(f'Put None into {self.username}\'s input queue')
        self.input_queue.put(None)
        logging.debug(f'Terminating process {self.username}')
        self.process.terminate()
        logging.debug(f'Stdin thread join {self.username}')
        self.stdin_thread is not None and self.stdin_thread.join()
        logging.debug(f'Stdout thread join {self.username}')
        self.stdout_thread is not None and self.stdout_thread.join()
        logging.debug(f'Disconnect complete {self.username}')

    def _send_data(self, data: str):
        logging.debug(f'Sending data -> {self.username} : {data} (connected: {self.connected})')
        if self.connected:
            self.input_queue.put(data)

    def send_chat(self, message: str):
        self._send_data(f'JSON{json.dumps(["chat", message])}')

    def send_whitelist_update(self):
        self._send_data(f'JSON{json.dumps(["updateSettings", self.list_type, self.strict, self.quiet, self.list])}')


# source: https://github.com/python/cpython/blob/main/Lib/tkinter/scrolledtext.py
class ScrolledText(tk.Text):
    def __init__(self, master=None, **kw):
        self.frame = tk.Frame(master)
        self.vbar = tk.Scrollbar(self.frame)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)

        kw.update({'yscrollcommand': self.vbar.set})
        tk.Text.__init__(self, self.frame, **kw)
        self.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar['command'] = self.yview

        text_meths = vars(tk.Text).keys()
        methods = vars(tk.Pack).keys() | vars(tk.Grid).keys() | vars(tk.Place).keys()
        methods = methods.difference(text_meths)

        for m in methods:
            if m[0] != '_' and m != 'config' and m != 'configure':
                setattr(self, m, getattr(self.frame, m))

    def __str__(self):
        return str(self.frame)


class ConsoleLogger(logging.Handler):
    def __init__(self, console):
        super().__init__()
        self.console: tk.Text = console
        self.console.tag_config('DEBUG', foreground='gray')
        self.console.tag_config('INFO', foreground='black')
        self.console.tag_config('WARNING', foreground='darkorange1')
        self.console.tag_config('ERROR', foreground='orangered2')
        self.console.tag_config('CRITICAL', foreground='red4')

    # get index of last line in console text area
    # last_line = self.console_ta.index('end-1c linestart')
    def emit(self, record: logging.LogRecord):
        message = self.format(record)
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, message)
        self.console.tag_add(record.levelname, 'end-2c linestart', 'end-2c')
        self.console.configure(state=tk.DISABLED)
        self.console.see(tk.END)


class MainGUI:
    def __init__(self):
        self.accounts: dict[str, Account] = {}
        self.load_accounts()

        self.root = tk.Tk()
        self.root.geometry('900x650')
        self.root.title(f'Minecraft Account Manager v{__version__}')

        self.frame = tk.Frame(self.root)
        self.frame.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

        self.frame.grid_columnconfigure(0, weight=0)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=0)
        self.frame.grid_rowconfigure(1, weight=1)

        self.console_lf = ttk.LabelFrame(self.frame, text='Chat')
        self.console_lf.grid_columnconfigure(0, weight=1)
        self.console_lf.grid_columnconfigure(1, weight=0)
        self.console_lf.grid_columnconfigure(2, weight=0)
        self.console_lf.grid_rowconfigure(0, weight=1)
        self.console_lf.grid_rowconfigure(1, weight=0)
        self.console_lf.grid(row=1, column=1, padx=5, pady=(0, 5), sticky='nesw')

        # self.console_ta = ScrolledText(self.frame, wrap=tk.WORD, state=tk.DISABLED)
        self.console_ta = ScrolledText(self.console_lf, wrap='none', state=tk.DISABLED)
        self.console_ta.grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky='nsew')

        def limit_size(*args):
            value = self.commandline_var.get()
            if len(value) > 220:
                self.commandline_var.set(value[:220])

        self.commandline_var = tk.StringVar()
        self.commandline_var.trace('w', limit_size)

        self.commandline_entry = ttk.Entry(self.console_lf, textvariable=self.commandline_var)
        self.commandline_entry.grid(row=1, column=0, sticky='nesw', padx=5, pady=(0, 5))
        self.commandline_send = ttk.Button(self.console_lf, text='Send',
                                           command=lambda: self._send_chat(self.selected_account,
                                                                           self.commandline_entry.get()))
        self.commandline_send.grid(row=1, column=1, sticky='nesw', padx=(0, 5), pady=(0, 5))

        def __send_chat_all_bots():
            for acc in self.accounts.values():
                if acc.connected:
                    self._send_chat(acc, self.commandline_entry.get())

        self.commandline_send_all = ttk.Button(self.console_lf, text='Send all', command=__send_chat_all_bots)
        self.commandline_send_all.grid(row=1, column=2, sticky='nesw', padx=(0, 5), pady=(0, 5))

        self.frame_col1 = tk.Frame(self.frame)
        self.frame_col1.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=5, pady=(0, 5))

        self.above_accounts_label = tk.Label(self.frame_col1, text='Loading...')
        self.above_accounts_label.pack()

        self.account_picker = ttk.Combobox(self.frame_col1, values=list(self.accounts.keys()), state='readonly')
        self.account_picker.pack()

        def account_changed(event):
            self.selected_account = self.accounts[self.account_picker.get()]
            self.update()

        self.account_picker.bind('<<ComboboxSelected>>', account_changed)
        self.account_picker.bind('<FocusIn>', lambda event: event.widget.master.focus_set())

        self.acc_add_remove_btn_holder = tk.Frame(self.frame_col1)
        self.acc_add_remove_btn_holder.pack(pady=(5, 0))

        self.add_acc_btn = ttk.Button(self.acc_add_remove_btn_holder, text='Add', command=self._add_account)
        self.add_acc_btn.pack(side=tk.LEFT)

        self.remove_acc_btn = ttk.Button(self.acc_add_remove_btn_holder, text='Remove', command=self._remove_account)
        self.remove_acc_btn.pack(side=tk.RIGHT)

        style = ttk.Style()
        style.configure('Custom.TRadiobutton',
                        focuscolor='none',
                        borderwidth=0,
                        highlightthickness=0)
        self.frame_WorBlist = tk.Frame(self.frame_col1)
        self.frame_WorBlist.pack(pady=(5, 0))

        self.whitelist_or_blacklist = tk.IntVar(value=0)

        def radiobtn_changed():
            i = self.whitelist_or_blacklist.get()
            self.selected_account.list_type = ('whitelist', 'blacklist')[i]
            self.selected_account.send_whitelist_update()
            self.save_accounts()
            self.update_remote()

        self.whitelist_radiobtn = ttk.Radiobutton(self.frame_WorBlist, text='Whitelist', value=0,
                                                  variable=self.whitelist_or_blacklist, style='Custom.TRadiobutton',
                                                  command=radiobtn_changed)
        self.blacklist_radiobtn = ttk.Radiobutton(self.frame_WorBlist, text='Blacklist', value=1,
                                                  variable=self.whitelist_or_blacklist, style='Custom.TRadiobutton',
                                                  command=radiobtn_changed)

        self.whitelist_radiobtn.pack(side=tk.LEFT, padx=(0, 5))
        self.blacklist_radiobtn.pack(side=tk.RIGHT)

        self.frame_col1_listbox = tk.Frame(self.frame_col1)
        self.frame_col1_listbox.pack(fill=tk.BOTH, pady=5, expand=True)

        self.list = tk.Listbox(self.frame_col1_listbox, justify='center')

        def onselect(evt):
            w = evt.widget
            sel = w.curselection()
            if sel:
                self.remove_username_btn.config(state='normal')
                self.remove_all_btn.config(state='normal')
            else:
                self.remove_username_btn.config(state='disabled')
                self.remove_all_btn.config(state='disabled')

        self.list.bind('<<ListboxSelect>>', onselect)

        # either first two lines or bottom two lines
        self.list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar = tk.Scrollbar(self.frame_col1_listbox, orient='vertical')
        # self.list.pack(fill=tk.BOTH, expand=True)
        # self.scrollbar = tk.Scrollbar(self.list, orient='vertical')

        self.scrollbar.config(command=self.list.yview)
        self.scrollbar.pack(side='right', fill='y')
        self.list.config(yscrollcommand=self.scrollbar.set)

        self.above_username_entry_label = tk.Label(self.frame_col1, text='Username (case sensitive):')
        self.above_username_entry_label.pack()

        self.username_entry = ttk.Entry(self.frame_col1)
        self.username_entry.pack(ipadx=10, pady=(0, 5))

        self.frame_col1_btnholder = tk.Frame(self.frame_col1)
        self.frame_col1_btnholder.pack()

        self.add_username_btn = ttk.Button(self.frame_col1_btnholder, text='Add', command=self._add)
        self.add_username_btn.pack(side=tk.LEFT)

        self.remove_username_btn = ttk.Button(self.frame_col1_btnholder, text='Remove', command=self._remove)
        self.remove_username_btn.pack(side=tk.RIGHT)

        self.frame_col1_btnholder_all = tk.Frame(self.frame_col1)
        self.frame_col1_btnholder_all.pack()

        self.add_all_btn = ttk.Button(self.frame_col1_btnholder_all, text='Add to all', command=self._add_all)
        self.add_all_btn.pack(side=tk.LEFT)

        self.remove_all_btn = ttk.Button(self.frame_col1_btnholder_all, text='Remove from all',
                                         command=self._remove_all)
        self.remove_all_btn.pack(side=tk.RIGHT)

        #

        self.labelframe_col2 = ttk.LabelFrame(self.frame, text='Options')
        self.labelframe_col2.grid(row=0, column=1, sticky='nsew', padx=5, pady=(0, 5))


        # self.get_selection_btn = ttk.Button(self.labelframe_col2, text='Get selection', command=lambda: print(self.list.curselection()))
        # self.get_selection_btn.pack()

        def __connect():
            if acc_username := self.account_picker.get():
                self._connect(self.accounts[acc_username])

        def __disconnect():
            if acc_username := self.account_picker.get():
                self._disconnect(self.accounts[acc_username])

        self.account_info_label = ttk.Label(self.labelframe_col2, text='')
        self.account_info_label.pack(side=tk.TOP)

        self.frame_options_buttons = tk.Frame(self.labelframe_col2)
        self.frame_options_buttons.pack()

        self.connect_acc_btn = ttk.Button(self.frame_options_buttons, text='Connect', command=__connect)
        self.connect_acc_btn.pack(side=tk.LEFT)

        self.connect_all_accs_btn = ttk.Button(self.frame_options_buttons, text='Connect all', command=self._connect_all)
        self.connect_all_accs_btn.pack(side=tk.LEFT)

        self.disconnect_acc_btn = ttk.Button(self.frame_options_buttons, text='Disconnect', command=__disconnect)
        self.disconnect_acc_btn.pack(side=tk.LEFT)

        self.disconnect_all_accs_btn = ttk.Button(self.frame_options_buttons, text='Disconnect all',
                                                  command=self._disconnect_all)
        self.disconnect_all_accs_btn.pack(side=tk.LEFT)

        self.frame_toggles = tk.Frame(self.labelframe_col2)
        self.frame_toggles.pack()

        def _toggle_strict():
            self.selected_account.strict = not self.selected_account.strict
            self.selected_account.send_whitelist_update()
            self.update()

        self.toggle_strict = ttk.Checkbutton(self.frame_toggles, text='Strict', command=_toggle_strict)
        self.toggle_strict.state(['!alternate'])
        self.toggle_strict.pack(side=tk.LEFT)


        def _toggle_quiet():
            self.selected_account.quiet = not self.selected_account.quiet
            self.selected_account.send_whitelist_update()
            self.update()

        self.toggle_quiet = ttk.Checkbutton(self.frame_toggles, text='Quiet', command=_toggle_quiet)
        self.toggle_quiet.state(['!alternate'])
        self.toggle_quiet.pack(side=tk.LEFT)

        self.frame_account_note = tk.Frame(self.labelframe_col2)
        self.frame_account_note.pack(expand=True, fill=tk.X, padx=(10, 10), pady=(0, 5))

        self.note_label = ttk.Label(self.frame_account_note, text='Note:')
        self.note_label.pack(side=tk.LEFT)

        def note_stringvar_callback(*args):
            self.selected_account.note = self.note_entry_stringvar.get()
            self.save_accounts()
            self.update_remote()

        self.note_entry_stringvar = tk.StringVar()
        self.note_entry_stringvar.trace('w', note_stringvar_callback)
        self.note_entry = ttk.Entry(self.frame_account_note, textvariable=self.note_entry_stringvar)
        self.note_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

        self.selected_account: Optional[Account] = None
        self.update()

        self.textarea_lines = queue.Queue()

        def keep_updating():
            while True:
                self.update_remote()
                time.sleep(3.1)

        t = threading.Thread(target=keep_updating, name='ThreadKeepUpdating', daemon=True)
        t.start()

    def _send_chat(self, account: Account, line: str):
        account.send_chat(line)
        # self.commandline_entry.delete(0, tk.END)
        # self.add_line_to_textarea(f'You: {line}')

    def add_line_to_textarea(self, line):
        line = f'{line.strip()}\n'
        self.console_ta.configure(state=tk.NORMAL)
        self.console_ta.insert(tk.END, line)
        self.console_ta.configure(state=tk.DISABLED)

        if self.console_ta.vbar.get()[1] > 0.999:
            self.console_ta.see(tk.END)

    def clear_textarea(self):
        self.console_ta.configure(state=tk.NORMAL)
        self.console_ta.delete(1.0, tk.END)
        self.console_ta.configure(state=tk.DISABLED)

    def add_pending_textarea_lines(self):
        while not self.textarea_lines.empty():
            self.add_line_to_textarea(self.textarea_lines.get())

    def _connect(self, account: Account):
        if not account.connected:
            logging.debug(f'Started connecting {account.username}')
            account.connect()
            logging.debug(f'{account.username} connected successfully')
            self.update()

    def _disconnect(self, account: Account):
        if account.connected:
            logging.info(f'Disconnecting {account.username}')
            account.disconnect()
            logging.info(f'{account.username} disconnected successfully')
            self.update()

    def _connect_all(self):
        for i, acc in enumerate(self.accounts.values()):
            self.root.after(11000 * i, (lambda _account: lambda: self._connect(_account))(acc))

    def _disconnect_all(self):
        for acc in self.accounts.values():
            self._disconnect(acc)

    def _add_account(self):
        def on_confirm():
            if username := entry.get():
                self.selected_account = self.accounts[username] = Account(username, self, 'whitelist', [], False, False, '')
                self.account_picker['values'] = list(self.accounts.keys())
                self.account_picker.set(username)
                self.update()
                popup.destroy()
            else:
                messagebox.showerror('Error', 'Please enter a valid username.')
                popup.lift()
                entry.focus_force()

        messagebox.showinfo(
            'Add account',
            f'You are now going to add a new account. Please make sure the username you enter is CORRECT '
            'and CaSe-SeNsItiVe because it is passed to the bot so it knows what their own name is and so it can '
            'differentiate between other bots and real players! When you connect this account to Hypixel for the '
            'first time, you will be prompted to log in to Microsoft through a 8 digit code.\n\nPress OK to continue.'
        )
        popup = tk.Toplevel(self.root)
        popup.title('Add account')
        popup.geometry('300x100')
        popup.resizable(False, False)
        ttk.Label(popup, text='Enter the username of the account:').pack(pady=5)
        (entry := ttk.Entry(popup)).pack(pady=(0, 5))
        ttk.Button(popup, text='Confirm', command=on_confirm).pack(pady=5)

    def _remove_account(self):
        if (account_username := self.account_picker.get()) and \
                messagebox.askyesno('Remove account', f'Are you sure you want to remove {account_username}?'):
            del self.accounts[account_username]
            self.account_picker['values'] = list(self.accounts.keys())
            self.account_picker.set('')
            self.selected_account = None
            self.update()

    def _add(self):
        username = self.username_entry.get()
        if username and username not in (l := self.selected_account.list):
            l.append(username)
            self.selected_account.send_whitelist_update()
            self.update()

    def _remove(self):
        if sel := self.list.curselection():
            username = self.list.get(sel[0])
            self.selected_account.list.remove(username)
            self.selected_account.send_whitelist_update()
            self.update()

    def _add_all(self):
        if username := self.username_entry.get():
            for acc in self.accounts.values():
                if username not in acc.list:
                    acc.list.append(username)
                    acc.send_whitelist_update()
            self.update()

    def _remove_all(self):
        if sel := self.list.curselection():
            username = self.list.get(sel[0])
            for acc in self.accounts.values():
                if username in acc.list:
                    acc.list.remove(username)
                    acc.send_whitelist_update()
            self.update()

    def update(self):
        self.list.delete(0, tk.END)
        self.above_accounts_label.config(text='Online accounts: {}/{}'.format(
            len([acc for acc in self.accounts.values() if acc.connected]),
            len(self.accounts)
        ))
        if self.selected_account is None:
            self.whitelist_radiobtn.config(state='disabled')
            self.blacklist_radiobtn.config(state='disabled')
            self.list.config(state='disabled')
            self.remove_acc_btn.config(state='disabled')
            self.add_username_btn.config(state='disabled')
            self.remove_username_btn.config(state='disabled')
            self.remove_all_btn.config(state='disabled')
            self.connect_acc_btn.config(state='disabled')
            self.disconnect_acc_btn.config(state='disabled')
            self.commandline_send.config(state='disabled')
            self.commandline_send_all.config(state='disabled')
            self.toggle_strict.state(['disabled'])
            self.toggle_quiet.state(['disabled'])
            self.console_lf.config(text='Chat')
            self.account_info_label.config(text='No account selected')
            self.note_entry.config(state='disabled')
        else:
            self.whitelist_radiobtn.config(state='normal')
            self.blacklist_radiobtn.config(state='normal')
            self.list.config(state='normal')
            self.remove_acc_btn.config(state='normal')
            self.add_username_btn.config(state='normal')
            self.connect_acc_btn.config(state='normal')
            self.disconnect_acc_btn.config(state='normal')
            self.commandline_send_all.config(state='normal')
            self.console_lf.config(text=f'Chat')
            self.note_entry.config(state='normal')
            self.note_entry_stringvar.set(self.selected_account.note)
            if self.selected_account.strict:
                self.toggle_strict.state(['!disabled', 'selected'])
            else:
                self.toggle_strict.state(['!disabled', '!selected'])

            if self.selected_account.quiet:
                self.toggle_quiet.state(['!disabled', 'selected'])
            else:
                self.toggle_quiet.state(['!disabled', '!selected'])

            if self.list.curselection():
                self.remove_username_btn.config(state='normal')
                self.remove_all_btn.config(state='normal')
            else:
                self.remove_username_btn.config(state='disabled')
                self.remove_all_btn.config(state='disabled')
            if self.selected_account.connected:
                self.connect_acc_btn.config(state='disabled')
                self.disconnect_acc_btn.config(state='normal')
                self.commandline_send.config(state='normal')
                self.account_info_label.config(
                    text=f'lobby: {self.selected_account.lobby_name} {self.selected_account.lobby_number}, in party: {self.selected_account.in_party}')
            else:
                self.connect_acc_btn.config(state='normal')
                self.disconnect_acc_btn.config(state='disabled')
                self.commandline_send.config(state='disabled')
                self.account_info_label.config(text='Not connected to server')
            for i in self.selected_account.list:
                self.list.insert(tk.END, i)

            if self.selected_account.list_type == 'whitelist':
                self.whitelist_or_blacklist.set(0)
            else:
                self.whitelist_or_blacklist.set(1)

            self.clear_textarea()
            for line in self.selected_account.chat_history.copy():
                self.add_line_to_textarea(line)

        self.save_accounts()
        self.update_remote()

    def save_accounts(self):
        with open('accounts.json', 'w') as file:
            json.dump([acc.to_dict() for acc in self.accounts.values()], file, indent=2)

    def load_accounts(self):
        with open('accounts.json', 'r') as file:
            accounts = json.load(file)
        self.accounts.clear()
        for i in accounts:
            self.accounts[i['username']] = Account(i['username'], self, i['list_type'], i['list'], i.get('strict', False), i.get('quiet', False), i.get('note', ''))

    def update_remote(self):
        pass


def main():
    global NODE_PATH

    # Prepare necessary files and folders
    ensure_folder('logs')
    ensure_folder('accounts')

    # Setup logging
    handler1 = logging.FileHandler(filename=f'logs/GUI_{rightnow()}.log', mode='w', encoding='utf8')
    handler1.setLevel(logging.DEBUG)
    handler1.setFormatter(logging.Formatter('[%(asctime)s] [%(threadName)s #%(thread)d] [%(levelname)s] %(message)s'))

    handler2 = logging.StreamHandler()
    handler2.setLevel(logging.DEBUG)
    handler2.setFormatter(logging.Formatter('[%(asctime)s] [%(threadName)s #%(thread)d] [%(levelname)s] %(message)s'))

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler1)
    logger.addHandler(handler2)

    try:
        open('accounts.json').close()
    except FileNotFoundError:
        (f := open('accounts.json', 'w')).write('[]')
        f.close()
    except PermissionError as e:
        logging.exception('Permission Error', exc_info=e, stack_info=True)
        messagebox.showerror('Error',
                             f'Unable to access accounts.json, please run as administrator or move the folder elsewhere.\n\n{traceback.format_exc()}')
    except Exception as e:
        logging.exception('Unknown Error', exc_info=e, stack_info=True)
        messagebox.showerror('Error', f'An exception occurred.\n\n{traceback.format_exc()}')

    _node = os.environ.get('NODE_EXE')
    if _node is None:
        logging.warning('NODE_EXE environment variable not set, using \'node\'')
        NODE_PATH = 'node'
    else:
        logging.info(f'Using NODE_EXE: {_node}')
        NODE_PATH = _node

    cwd = Path().resolve()

    def report_callback_exception(self, exc, val, tb):
        traceback_text = ''.join(traceback.format_exception(exc, val, tb))
        traceback_text = traceback_text.replace(str(cwd), '.')
        messagebox.showerror("An exception occured", message=traceback_text)

    tk.Tk.report_callback_exception = report_callback_exception
    gui = MainGUI()

    if platform.python_implementation() == 'PyPy':
        gui.root.withdraw()
        messagebox.showerror('Error', 'Running the GUI is not supported with PyPy')
        sys.exit(1)

    try:
        logging.info('Starting GUI')
        gui.root.mainloop()
    except Exception as e:
        logging.critical('GUI Error', exc_info=e, stack_info=True)
        messagebox.showerror('Error', f'An exception occurred.\n\n{traceback.format_exc()}')


__name__ == '__main__' and main()
