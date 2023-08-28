from opcua import Client, ua
import time
from datetime import datetime, timedelta
import multiprocessing
import json
import sys
import os
#from pynput import keyboard

from colorama import Fore, Back

from readconfig import get_devices_processes
from datastore import DataStore
from displaylogs import print_log


c_idx_err_devdtime = 0
c_idx_bad_statuscode_devdtime = 1
c_idx_err_history_data = 2

c_idx_connected = 0
c_idx_dtime_con = 1
c_idx_attemptions = 2

с_count_err = 5

# Преобразвание идентификатора узла в формат для опроса по OPC UA
def transform_nodeid(nodeid):
    ls = nodeid.split(',')
    return "ns={}; i={}".format(ls[1].strip(), ls[0].strip())

# Чтение исторических данных
def read_history_data(process_num, devices_proc, logs_path, debug, debug_procs_nums, l):
    deb = (debug, debug_procs_nums, False)
    debug_forced = not (debug in [1, 3] and len(debug_procs_nums) != 0)  # Это не вывод на экран одного процесса
    deb_ = (debug, debug_procs_nums, debug_forced)

    hfile_logs = None
    if debug in [2, 3]:   # Включен режим записи в файл
        try:
            hfile_logs = open("{}/process{}.txt".format(logs_path, process_num), 'a')  # Открываем файл для записи логов
        except Exception as e:
            hfile_logs = None
            print_log(process_num, '', '', "Ошибка при открытии лог-файла ({})!!!".format(e), Back.RED, hfile_logs, deb, l)

    devs = '| '.join(["{}.{}".format(device["name"], sample["name"]) for device in devices_proc for sample in device["samples"]])
    print_log(process_num, '', '', "ПРОЦЕСС ЗАПУЩЕН: {}".format(devs), Fore.GREEN, hfile_logs, deb_, l)

    opcua_clients = []
    states_opcua_clients = []
    read_intervals = []
    count_read_errors = []
    time_offsets = []
    datetime_clear = datetime.now()
    for device in devices_proc:
        time_offsets.append([])
        count_read_errors.append([0, 0, []])
        for _ in device["samples"]:
            time_offsets[-1].append(0)
            count_read_errors[-1][2].append(0)

        read_intervals.append(int(device["readInterval"]))

        opcua_client = Client(device["uri"], timeout=1)
        opcua_clients.append(opcua_client)
        # client.set_user = "user"
        # client.set_password = "pw"
        connected = True
        try:
            opcua_client.connect()
            print_log(process_num, device["name"], '',  "OPC UA клиент успешно подключен".format(''), Fore.GREEN, hfile_logs, deb_, l)
        except Exception as e:
            connected = False
            print_log(process_num, device["name"], '', "Не удалось подключить OPC UA клиента ({})!!!".format(e), Fore.RED, hfile_logs, deb, l)

        states_opcua_clients.append([connected, datetime.utcnow(), 1])  # Состояние OPC UA клиента (подключен, время, номер попытки подключения)

    read_interval = min(read_intervals)

    prev_datetime_devices = []
    for device in devices_proc:
        prev_datetime_devices.append(datetime.utcnow() - timedelta(seconds=read_interval))

    device_idx_reconnect = -1

    datastore = DataStore(devices_proc, process_num, hfile_logs, debug, debug_procs_nums, l)  # Класс для сохранения исторических данных

    init = True
    try: 
        while True:
            # Очистка консоли раз в 10 минут
            if process_num == 1:
                if (datetime.now() - datetime_clear).total_seconds() > 600:
                    datetime_clear = datetime.now()
                    os.system("cls" if os.name=="nt" else "clear")
            try:
                # Расчет времени предыдущего цикла (добавление паузы при необходимости)
                if not init:
                    dv = 1000000000
                    diff_time = time_end_cycle - time_start_cycle  # Время предыдущего цикла в наносекундах
                    if diff_time > 4.5 * dv:               # Время цикла превышает допустимое время (будет потеря данных)
                        print_log(process_num, '', '', "КРИТИЧЕСКОЕ ВРЕМЯ ЦИКЛА ({:.2f} сек.). ЧАСТЬ ДАННЫХ БУДЕТ ПОТЕРЯНА!!!".format(diff_time / dv),
                                  Back.RED, hfile_logs, deb, l)
                        datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
                    elif diff_time > read_interval * dv:   # Время цикла превышает допустимое время (параметр readInterval в конфигурации)
                        print_log(process_num, '', '', "ПОГРАНИЧНОЕ ВРЕМЯ ЦИКЛА ({:.2f} сек.)!!!".format(diff_time / dv), Back.RED, hfile_logs, deb, l)
                    elif read_interval - diff_time / dv < 0.2:  # Нет запаса в 200 милисек.
                        print_log(process_num, '', '', "ВРЕМЯ ЦИКЛА ({:.2f} сек.) С НЕДОСТАТОЧНЫМ ЗАПАСОМ!!!".format(diff_time / dv),
                                  Back.YELLOW, hfile_logs, deb, l)
                    if diff_time < read_interval * dv:     # Время прошлого цикла меньше времени заданного цикла
                        ts = (read_interval * dv - diff_time) / dv
                        print_log(process_num, '', '', "Время предыдущего цикла - {:.2f} сек., необходима пауза - {:.2f}".format(diff_time / dv, ts),
                                  Fore.WHITE, hfile_logs, deb, l)
                        time.sleep(ts)

                time_start_cycle = time.time_ns()  # Время начала цикла

                is_reconnect = False
                count_notcon = sum([1 for device_idx in range(len(devices_proc)) if not states_opcua_clients[device_idx][0]]) # Кол-во не подключенных кл-в.
                for device_idx, device in enumerate(devices_proc):   # Проходимся по всем устройствам данного процесса
                    sample_name = ''
                    try:
                        # ---------- Переподключение OPC UA клиента -------------------------------------
                        if not states_opcua_clients[device_idx][c_idx_connected]:   # OPC UA клиент не подключен
                            if is_reconnect: continue                                            # В одном цикле допускается только одно переподключение
                            if count_notcon > 1 and device_idx == device_idx_reconnect: continue # К данному устройству пытались подключиться в пред. цикле
                            diff_time = datetime.utcnow() - states_opcua_clients[device_idx][c_idx_dtime_con]  # Прошло времени с момента подключения
                            if diff_time.total_seconds() > int(device["reconnectDelaySeconds"]):
                                is_reconnect = True; device_idx_reconnect = device_idx
                                connected = True
                                try:
                                    opcua_clients[device_idx].connect()
                                    print_log(process_num, device["name"], '', "OPC UA клиент успешно подключен".format(''),
                                              Fore.GREEN, hfile_logs, deb_, l)
                                except Exception as e:
                                    connected = False
                                    print_log(process_num, device["name"], '', "Не удалось подключить OPC UA клиента. Попытка подключения №{} ({})!!!".
                                              format(states_opcua_clients[device_idx][c_idx_attemptions], e), Fore.RED, hfile_logs, deb, l)
                                # Обновляем состояние OPC UA клиента и время подключения
                                states_opcua_clients[device_idx][c_idx_connected] = connected
                                states_opcua_clients[device_idx][c_idx_dtime_con] = datetime.utcnow()
                                if connected:
                                    states_opcua_clients[device_idx][c_idx_attemptions] = 1
                                else: states_opcua_clients[device_idx][c_idx_attemptions] += 1

                        if not states_opcua_clients[device_idx][c_idx_connected]: continue   # Клиент не подключен
                        # ------------------------------------------------------------------------------------------------------
                        fail_read = False
                        try:
                            datetime_node = opcua_clients[device_idx].get_node(transform_nodeid(device["datetime_node_id"]))
                            data = datetime_node.get_data_value()
                        except Exception as e:
                            print_log(process_num, device["name"], '', "Ошибка при чтении времени контроллера ({})!!!".format(e),
                                      Back.RED, hfile_logs, deb, l)
                            fail_read = True
                            count_read_errors[device_idx][c_idx_err_devdtime] += 1
                            if count_read_errors[device_idx][c_idx_err_devdtime] == 2:
                                datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
                        else: count_read_errors[device_idx][c_idx_err_devdtime] = 0

                        if not fail_read:
                            print_log(process_num, device["name"], '', "Статус значения времени контроллера - {}".format(data.StatusCode.name),
                                      Fore.LIGHTBLUE_EX, hfile_logs, deb, l)

                        if not fail_read and data.StatusCode.is_good():  # Значение времени контроллера прочитано и имеет хорошее качество
                            count_read_errors[device_idx][c_idx_bad_statuscode_devdtime] = 0

                            datetime_device = data.Value.Value  # Текущее время устройства
                            prev_datetime = prev_datetime_devices[device_idx]   # Предыдущее время устройства, если не 1-й цикл
                            prev_datetime_devices[device_idx] = datetime_device
                            if init: continue  # Если 1-й цикл

                            if abs((prev_datetime - datetime_device).total_seconds()) > 15:   # На компьютере или ПЛК перевели часы
                                print_log(process_num, device["name"], '', "НЕДОПУСТИМАЯ РАЗНИЦА ТЕКУЩЕГО И ПРЕДЫДУЩЕГО ВРЕМЕНИ!!!".
                                          format(read_interval), Back.RED, hfile_logs, deb, l)
                                datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
                                continue
                            print_log(process_num, device["name"], '', "Текущее время контроллера: {}, предыдущее время: {}".
                                      format(datetime_device, prev_datetime), Fore.CYAN, hfile_logs, deb, l)
                            # Разсинхронизация по времени между данным компьютером и контроллером
                            if abs((datetime.utcnow() - datetime_device).total_seconds()) > 60:
                                print_log(process_num, device["name"], '', "НЕТ СИНХРОНИЗАЦИИ ВРЕМЕНИ МЕЖДУ КОМПЬЮТЕРОМ И КОНТРОЛЛЕРОМ!!!".format(''),
                                          Back.RED, hfile_logs, deb, l)
                                datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
                                continue

                            for sample_idx, sample in enumerate(device["samples"]):       # Проходимся по всем выборкам устройства
                                try:
                                    fail_read = False
                                    try:
                                        data_node = opcua_clients[device_idx].get_node(transform_nodeid(sample["node_id"]))

                                        details = ua.ReadRawModifiedDetails()
                                        details.IsReadModified = False
                                        details.StartTime = prev_datetime - timedelta(seconds=time_offsets[device_idx][sample_idx]) -\
                                            timedelta(milliseconds=150)  # 150 мсек. - запаздывание формирования выборки
                                        details.EndTime = datetime_device
                                        details.NumValuesPerNode = 0
                                        details.ReturnBounds = False
                                        result = data_node.history_read(details)
                                        result.StatusCode.check()
                                        history_data = result.HistoryData.DataValues
                                    except Exception as e:
                                        fail_read = True
                                        print_log(process_num, device["name"], sample["name"], "Ошибка при чтении исторических данных ({})!!!".format(e),
                                                  Back.RED, hfile_logs, deb, l)
                                        if count_read_errors[device_idx][c_idx_err_history_data][sample_idx] == 0:
                                            time_offsets[device_idx][sample_idx] = read_interval  # Если 1-я ошибка в след. цикле читаем за двойной интервал
                                        else: time_offsets[device_idx][sample_idx] = 0
                                        count_read_errors[device_idx][c_idx_err_history_data][sample_idx] += 1
                                        if count_read_errors[device_idx][c_idx_err_history_data][sample_idx] == 2:
                                            datastore.close(device_idx, sample_idx, deb)  # Закрываем хранилище данных
                                    else:
                                        time_offsets[device_idx][sample_idx] = 0
                                        count_read_errors[device_idx][c_idx_err_history_data][sample_idx] = 0
                                    # Сохраняем исторические данные
                                    if not fail_read: datastore.save(device_idx, sample_idx, history_data, data.StatusCode)
                                except Exception as e:
                                    print_log(process_num, device["name"], sample["name"], "Исключение при обработке выборки ({})!!!".format(e),
                                              Back.RED, hfile_logs, deb, l)
                                    datastore.close(device_idx, sample_idx, deb)  # Закрываем хранилище данных
                                time.sleep(0.01)   # Небольшая пауза между чтением данных выборки (10 милисек.)
                        else:  # Плохое качество значения времени контроллера или ошибка чтения времени
                            if not fail_read:   # Если не ошибка чтения
                                # Инициализация данных OPC UA сервера, ошибка ПЛК, отключены датчики или ошибка конфигурации
                                if data.StatusCode.name in ["Bad_WaitingForInitialData", "Bad_DeviceFailure", "Bad_SensorFailure", "Bad_ConfigurationError"]:
                                    datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
                                elif data.StatusCode.name in ["Bad_NotConnected", "Bad_NoCommunication", "Bad_OutOfService"]:
                                    datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
                                    count_read_errors[device_idx][c_idx_bad_statuscode_devdtime] += 1

                        # Подряд идут ошибки или приходит плохое качество
                        if count_read_errors[device_idx][c_idx_err_devdtime] == с_count_err or \
                                count_read_errors[device_idx][c_idx_bad_statuscode_devdtime] == с_count_err:
                            count_read_errors[device_idx][c_idx_err_devdtime] = 0
                            count_read_errors[device_idx][c_idx_bad_statuscode_devdtime] = 0
                            if states_opcua_clients[device_idx][c_idx_connected]:   # Клиент подключен
                                states_opcua_clients[device_idx][c_idx_connected] = False
                                states_opcua_clients[device_idx][c_idx_dtime_con] = datetime.utcnow()
                                try:
                                    opcua_clients[device_idx].disconnect()  # Закрываем соединение
                                    print_log(process_num, device["name"], '', "OPC UA клиент отключен".format(''), Fore.YELLOW, hfile_logs, deb, l)
                                except Exception as e:
                                    print_log(process_num, '', '', "Ошибка при отключении OPC UA клиента ({})!!!".format(e),
                                    Fore.RED, hfile_logs, deb, l)
                    except Exception as e:
                        print_log(process_num, device["name"], sample_name, "Исключение при обработке устройства ({})!!!".format(e),
                                  Fore.RED, hfile_logs, deb, l)
                        datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
            except Exception as e:
                print_log(process_num, '', '', "Исключение в основном цикле программы ({})!!!".format(e), Back.RED, hfile_logs, deb, l)
            finally:
                init = False
                time_end_cycle = time.time_ns()  # Время конца цикла
    finally:
        # Закрываем всех OPC UA клиентов
        for device_idx, device in enumerate(devices_proc):  # Проходимся по всем устройствам данного процесса
            datastore.close(device_idx, -1, deb)  # Закрываем хранилище данных
            if states_opcua_clients[device_idx][0]:  # OPC UA клиент подключен
                opcua_clients[device_idx].disconnect()
        print_log(process_num, '', '', "ПРОЦЕСС ЗАВЕРШЕН".format(''), Fore.GREEN, hfile_logs, deb, l)
        if hfile_logs != None: hfile_logs.close()  # Закрываем файл логов


def main(cfg_filename, debug, debug_procs_nums):
    logs_path = "logs"
    try:
        if debug in [2, 3]:  # Включен режим записи в файл
            if not os.path.exists(logs_path): os.mkdir(logs_path)
    except Exception as e:
        print("Ошибка при создании директории для лог-файлов ({})!!!".format(e))

    lock = multiprocessing.Lock()   # Блокировщик для синхронизации вывода логов на экране

    devices_processes = get_devices_processes(cfg_filename, debug) # Список устройств (контроллеров), распределенные по разным процессам

    processes = []
    for process_idx, devices_proc in enumerate(devices_processes):
        time.sleep(0.15)        # Пауза, чтобы между процессами был промежуток времени (для отображения логов) (не обязательно)
        if len(devices_proc) == 0: break   # Процессу не назначены устройства
        process = multiprocessing.Process(target=read_history_data, args=(process_idx + 1, devices_proc, logs_path, debug, debug_procs_nums, lock))
        processes.append(process)
        process.daemon = True
        #os.system("taskset -p -c %d %d" % (process_idx % multiprocessing.cpu_count(), os.getpid()))
        process.start()

    for process in processes:
        process.join()           # Ожидаем завершения процесса


if __name__ == '__main__':
    if "win" in sys.platform.lower():
        multiprocessing.freeze_support()

    debug = 0   # 0 - режим отладки отключен, 1 - сообщения на экране, 2 - запсиь в файл, 3 - на экране и запись в файл
    debug_procs_nums = []   # Список номеров процессов, отображаемых на экране
    if len(sys.argv) > 1:   # Заданы параметры запуска программы
        debug = int(sys.argv[1])
        if len(sys.argv) > 2:
            st = sys.argv[2]
            if '[' in st and ']' in st:
                idx1 = st.index('[')
                debug_procs_nums = json.loads(st[idx1:])  # Список процессов для отладки

    #print("Debug mode - {}".format(debug))
    #print("debug procs nums - {}".format(debug_procs_nums))

    main("config.xml", debug, debug_procs_nums)
