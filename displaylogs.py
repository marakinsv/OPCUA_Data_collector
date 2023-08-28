from datetime import datetime

import colorama
from colorama import Fore, Back
colorama.init(autoreset=True)


# Отображение и сохранение логов
def print_log(process_num, device_name, sample_name, text, color_code, hfile_logs, deb, lock):
    debug, debug_procs_nums, debug_forced = deb

    debug_proc = debug in [1, 3] and (process_num in debug_procs_nums or len(debug_procs_nums) == 0)  # Режим отладки для указанного процесса

    header = "Process {}".format(process_num)
    if device_name != '' : header += ".{}".format(device_name)
    if sample_name != '': header += ".{}".format(sample_name)
    msg = "{} {}: {}".format(datetime.utcnow(), header, text)

    if debug in [2, 3] and hfile_logs != None:    # Включен режим записи в файл
        try:
            hfile_logs.write(msg + "\n")
            hfile_logs.flush()
        except Exception as e:
            print("Process {}: Error write in file of logs ({})!!!".format(process_num, e))

    if debug_proc or debug_forced:
        lock.acquire()  # Блокируем доступ другим процессам к секции нииже
        try:
            if color_code in [Back.YELLOW, Back.RED]:
                print(color_code + Fore.BLACK + msg)
            else:
                print(color_code + msg)
        finally:
            lock.release()  # Разблокируем доступ

    if debug in [0, 2]:   # Режим отладки выключен или включен режим записи в файл
        if color_code in [Back.YELLOW, Fore.YELLOW, Back.RED, Fore.RED]:  # Отображаем предупреждения и ошибки всех процессов
            lock.acquire()      # Блокируем доступ другим процессам к секции нииже
            try:
                if color_code in [Fore.YELLOW, Fore.RED]:
                    print(color_code + msg)
                else: print(color_code + Fore.BLACK + msg)
            finally:
                lock.release()  # Разблокируем доступ