from colorama import Fore, Back

from displaylogs import print_log

import os
import struct
from datetime import datetime


c_ext_file_header = ".mera"
c_ext_file_data = ".dat"

c_idx_filename_header = 0
c_idx_filename_data = 1
c_idx_datetime = 2

c_idx_first_timestamp = 0
c_idx_last_timestamp = 1
c_idx_count_values = 2


# Класс для сохранения исторических данных
class DataStore(object):
    # Конструктор
    def __init__(self, devices_proc, process_num, hfile_logs, debug, debug_procs_nums, l):
        super().__init__()

        self.devices_proc = devices_proc
        self.process_num = process_num
        self.hfile_logs = hfile_logs
        self.debug = debug
        self.debug_procs_nums = debug_procs_nums
        self.l = l

        self.inits = []                     # 1-е сохранения данных
        self.dir_exists = []                # Есть ли директория для сохранения файлов
        self.filenames = []                 # Имена файлов данных, в к-е идет запись исторических значений, и время их создания
        self.headers = []                   # Содержание заголовочных файлов
        self.data_calc_freq = []            # Данные для расчета частоты дискретизации за промежуток времени
        self.avg_frequencies = []           # Средние частоты выборок
        self.timestamps_last_blocks = []    # Временные метки последних блоков данных (полученных на предыдущем цикле)
        self.indexes_blocks = []            # Индексы блоков данных, с которого начинаются новые блоки данных, не пересекающихся с пред. циклом
        for device_idx in range(len(devices_proc)):
            self.inits.append([])
            self.dir_exists.append([])
            self.filenames.append([])
            self.headers.append([])
            self.data_calc_freq.append([])
            self.avg_frequencies.append([])
            self.timestamps_last_blocks.append([])
            self.indexes_blocks.append([])
            for _ in devices_proc[device_idx]["samples"]:
                self.inits[device_idx].append(True)
                self.dir_exists[device_idx].append(False)
                self.filenames[device_idx].append(['', '', None])
                self.headers[device_idx].append('')
                self.data_calc_freq[device_idx].append([None, None, 0])
                self.avg_frequencies[device_idx].append(None)
                self.timestamps_last_blocks[device_idx].append(None)
                self.indexes_blocks[device_idx].append(0)

    # Проверка наличия директории к файлам
    def _dir_exists(self, device, sample, deb):
        filepath = device["HomeDir"] + sample["subdir"]  # Путь к файлу
        if os.path.exists(filepath): return True
        try:
            ls = filepath.split("\\")
            path = ls[0]
            for i in range(1, len(ls)):
                path += '/' + ls[i]
                if not os.path.exists(path): os.mkdir(path)
            return True
        except Exception as e:
            print_log(self.process_num, device["name"], sample["name"],
                      "Исключение при создании директории для файлов выборки ({})!!!".format(e), Back.RED, self.hfile_logs, deb, self.l)
        return False

    # Сохранение исторических данных
    def save(self, device_idx, sample_idx, history_data, status_code):
        deb = (self.debug, self.debug_procs_nums, False)
        debug_forced = not (self.debug in [1, 3] and len(self.debug_procs_nums) != 0)  # Это не вывод на экран одного процесса
        deb_ = (self.debug, self.debug_procs_nums, debug_forced)
        try:
            device = self.devices_proc[device_idx]
            sample = self.devices_proc[device_idx]["samples"][sample_idx]

            if self.inits[device_idx][sample_idx]:                         # 1-е сохранение данных
                self.dir_exists[device_idx][sample_idx] = self._dir_exists(device, sample, deb)  # Проверяем есть ли директория для файлов

            if history_data == None:
                print_log(self.process_num, device["name"], sample["name"], "Отсутствуют блоки исторических данных".format(''),
                          Fore.YELLOW, self.hfile_logs, deb, self.l)
                self.close(device_idx, sample_idx, deb)   # Закрываем хранилище данных
            elif len(history_data) == 0:
                print_log(self.process_num, device["name"], sample["name"], "Количество блоков исторических данных равно 0".format(''),
                          Fore.YELLOW, self.hfile_logs, deb, self.l)
                self.close(device_idx, sample_idx, deb)  # Закрываем хранилище данных
            elif len(history_data) == 1:
                if history_data[0].SourceTimestamp <= self.timestamps_last_blocks[device_idx][sample_idx]: # Данные уже сохраняли
                    return
            else:
                self.indexes_blocks[device_idx][sample_idx] = 0
                for block_idx in range(len(history_data)):
                    if self.timestamps_last_blocks[device_idx][sample_idx] == None: break  # Нет временной метки блоков, полученных на пред. цикле

                    if history_data[block_idx].SourceTimestamp > self.timestamps_last_blocks[device_idx][sample_idx]:  # Нашли 1-й новый блок данных
                        self.indexes_blocks[device_idx][sample_idx] = block_idx
                        break
                # Сохраняем временную метку последнего блока данных
                self.timestamps_last_blocks[device_idx][sample_idx] = history_data[-1].SourceTimestamp

                idx_start = self.indexes_blocks[device_idx][sample_idx]
                count_values = sum([len(history_data[idx].Value.Value) for idx in range(idx_start, len(history_data))])  # Кол-во прочитанных значений
                if len(history_data) > 1:
                    frequency = count_values / (history_data[-1].SourceTimestamp - history_data[idx_start].SourceTimestamp).total_seconds() # Частота дискр.
                else: frequency = 0.0

                print_log(self.process_num, device["name"], sample["name"], "Кол-во блоков: {}, кол-во значений: {}, диапазон: {} - {}".
                          format(len(history_data) - idx_start, count_values, history_data[idx_start].SourceTimestamp,
                                 history_data[-1].SourceTimestamp), Fore.CYAN, self.hfile_logs, deb, self.l)

                if not self.dir_exists[device_idx][sample_idx]:
                    filepath = device["HomeDir"] + sample["subdir"]  # Путь к файлу
                    print_log(self.process_num, device["name"], sample["name"], "Не найдена директория '{}' для файлов выборки!!!".format(filepath),
                              Back.RED, self.hfile_logs, deb, self.l)
                    return
                # В конфигурации задано брать фиксированную частоту
                if int(sample["IsFixedFrequency"]):           # Берем указанную в конфигурации частоту
                    fixed_frequency = int(sample["FixedFrequency"])
                else:
                    fixed_frequency = None

                    if self.avg_frequencies[device_idx][sample_idx] == None:
                        self.avg_frequencies[device_idx][sample_idx] = frequency

                    '''avg_freq = self.avg_frequencies[device_idx][sample_idx]
                    percent_deviation = abs((1.0 - frequency / avg_freq) * 100.0)  # Разница между текущей и средней частотой
                    if percent_deviation > float(sample["MaxFrequencyDeviationPercent"]):
                        print_log(self.process_num, device["name"], sample["name"],
                                "Превышение допустимого процента отклонения частоты дискр. ({:.1f}%, freq={:.2f}, avg_freq={:.2f}))".
                                format(percent_deviation, frequency, avg_freq), Fore.YELLOW, self.hfile_logs, deb, self.l)
                        self.close(device_idx, sample_idx, deb)  # Закрываем хранилище данных
                        return'''
                    # Обновляем среднюю частоту
                    if frequency != 0.0:
                        self.avg_frequencies[device_idx][sample_idx] = (self.avg_frequencies[device_idx][sample_idx] + frequency) / 2
                try:
                    time_is_up = False
                    if self.filenames[device_idx][sample_idx][c_idx_datetime] != None:
                        if (history_data[idx_start].SourceTimestamp - self.filenames[device_idx][sample_idx][c_idx_datetime]).total_seconds() >\
                                int(sample["save_length"]) * 60: time_is_up = True
                    # ========================= Создание нового заголовочного файла ===========================
                    if self.filenames[device_idx][sample_idx][c_idx_filename_header] == '' or time_is_up:  # Файл еще не создан или вышло время записи в файл
                        self.close(device_idx, sample_idx, deb)  # Закрываем хранилище данных
                        # Создаем заголовочный файл и получаем имя файла данных
                        filename_header, filename_data = \
                            self.create_header_file(device_idx, sample_idx, history_data[idx_start].SourceTimestamp, fixed_frequency)

                        self.filenames[device_idx][sample_idx][c_idx_filename_header] = filename_header
                        self.filenames[device_idx][sample_idx][c_idx_filename_data] = filename_data
                        self.filenames[device_idx][sample_idx][c_idx_datetime] = history_data[idx_start].SourceTimestamp

                        # Инициализируем данные для расчета частоты дискретизации
                        self.data_calc_freq[device_idx][sample_idx][c_idx_first_timestamp] = history_data[idx_start].SourceTimestamp
                        self.data_calc_freq[device_idx][sample_idx][c_idx_last_timestamp] = history_data[-1].SourceTimestamp
                        self.data_calc_freq[device_idx][sample_idx][c_idx_count_values] = count_values

                        # ========================= Удаление устаревших файлов (только 3 пары) ===========================
                        self.delete_old_files(3, device_idx, sample_idx, history_data[idx_start].SourceTimestamp, deb)
                    else:
                        # Обновляем данные для расчета частоты дискретизации
                        self.data_calc_freq[device_idx][sample_idx][c_idx_last_timestamp] = history_data[-1].SourceTimestamp
                        self.data_calc_freq[device_idx][sample_idx][c_idx_count_values] += count_values
                except Exception as e:
                    print_log(self.process_num, device["name"], sample["name"], "Исключение при создании заголовочного файла ({})!!!".format(e),
                              Back.RED, self.hfile_logs, deb, self.l)
                # ============================== Обновление заголовочного файла (обновление значения частоты) ===============================
                try:
                    if not int(sample["IsFixedFrequency"]):
                        self.update_header_file(device_idx, sample_idx, self.filenames[device_idx][sample_idx][c_idx_filename_header])
                except Exception as e:
                    print_log(self.process_num, device["name"], sample["name"], "Исключение при обновлении заголовочного файла ({})!!!".format(e),
                              Back.RED, self.hfile_logs, deb, self.l)
                # ============================== Запись значений в файл данных ===============================
                try:
                    self.write_history_data(self.filenames[device_idx][sample_idx][c_idx_filename_data], history_data, device_idx, sample_idx, deb)
                except Exception as e:
                    print_log(self.process_num, device["name"], sample["name"], "Исключение при записи данных в файл ({})!!!".format(e),
                              Back.RED, self.hfile_logs, deb, self.l)
        except Exception as e:
            print_log(self.process_num, '', '', "Исключение при сохранении данных выборки ({})!!!".format(e), Back.RED, self.hfile_logs, deb, self.l)
            self.close(device_idx, sample_idx, deb)  # Закрываем хранилище данных

        self.inits[device_idx][sample_idx] = False

    # Закрыть хранилище данных
    def close(self, device_idx, sample_idx, deb):
        device = self.devices_proc[device_idx]
        if sample_idx != -1:
            if self.filenames[device_idx][sample_idx][c_idx_filename_header] != '':
                sample = self.devices_proc[device_idx]["samples"][sample_idx]

                self.filenames[device_idx][sample_idx][c_idx_filename_header] = ''
                self.filenames[device_idx][sample_idx][c_idx_filename_data] = ''
                self.filenames[device_idx][sample_idx][c_idx_datetime] = None

                print_log(self.process_num, device["name"], sample["name"], "Закрыли хранилище данных".format(''),
                          Fore.YELLOW,self.hfile_logs, deb, self.l)
        else:    # Необходимо закрыть хранилища данных всех выборок указанного устройства
            for idx_sample in range(len(self.devices_proc[device_idx]["samples"])):
                if self.filenames[device_idx][idx_sample][c_idx_filename_header] != '':
                    self.filenames[device_idx][idx_sample][c_idx_filename_data] = ''
                    self.filenames[device_idx][idx_sample][c_idx_filename_header] = ''
                    self.filenames[device_idx][idx_sample][c_idx_datetime] = None

                    print_log(self.process_num, device["name"], '', "Закрыли хранилища данных всех выборок".format(''),
                              Fore.YELLOW, self.hfile_logs, deb, self.l)

    # Возвращает имя заголовочного файла и имя файла данных
    def build_filenames(self, device_idx, sample_idx, datetime_created):
        device = self.devices_proc[device_idx]
        sample = self.devices_proc[device_idx]["samples"][sample_idx]

        filepath = (device["HomeDir"] + sample["subdir"]).replace("\\", '/')  # Путь к файлу

        filename = datetime_created.strftime("%Y_%m_%d_%H%M%S") #+ "_" + str(int(sample["save_length"])) + "m"

        return ("{}/{}{}".format(filepath, filename, c_ext_file_header), "{}/{}{}".format(filepath, filename, c_ext_file_data), filename)

    # Создать заголовочный файл формата "Мера"
    def create_header_file(self, device_idx, sample_idx, datetime_created, fixed_frequency):
        device = self.devices_proc[device_idx]
        sample = self.devices_proc[device_idx]["samples"][sample_idx]

        filename_header, filename_data, filename = self.build_filenames(device_idx, sample_idx, datetime_created)

        if fixed_frequency != None:
            freq = fixed_frequency
        else: freq = self.avg_frequencies[device_idx][sample_idx]

        self.headers[device_idx][sample_idx] = "[MERA]\n"\
                 "Test=npp_tik\n"\
                 "Prod={}\n".format(device["name"]) + ''\
                 "Date={}\n".format(datetime_created.strftime("%d.%m.%y")) + ''\
                 "Time={}.{}\n\n".format(datetime_created.strftime("%H:%M:%S"), int(datetime_created.microsecond / 10000)) + ''\
                 "[{}]\n".format(filename) + ''\
                 "Char={}\n".format(sample["name"]) + ''\
                 "StartTime={}\n".format(datetime_created.strftime("%H:%M:%S"), int(datetime_created.microsecond / 1000)) + ''\
                 "XUnits=с\n" \
                 "YUnits={}\n".format(sample["EngUnit"]) + ''\
                 "Start=0.0\n"\
                 "Freq={:.2f}\n".format(freq) + ''\
                 "YFormat=R4\n"

        with open(filename_header, "w") as fw:
            fw.write(self.headers[device_idx][sample_idx])

        return (filename_header, filename_data)

    # Обновить данные заголовочного файла
    def update_header_file(self, device_idx, sample_idx, filename):
        header = self.headers[device_idx][sample_idx]   # Текущее содержимое заголовочного файла

        param_name = "Freq"  # Имя изменяемого параметра

        dif_seconds = (self.data_calc_freq[device_idx][sample_idx][c_idx_last_timestamp] -
                       self.data_calc_freq[device_idx][sample_idx][c_idx_first_timestamp]).total_seconds()

        if dif_seconds > 0:
            frequency = self.data_calc_freq[device_idx][sample_idx][c_idx_count_values] / dif_seconds
        else: frequency = 0.0

        txt = header[header.index(param_name + '=') : ]

        pos1 = header.index(txt) + len(param_name + '=')
        pos2 = pos1 + header[pos1:].index('\n')

        old_frequency = header[pos1: pos2]     # Текущая частота в заголовочном файле

        self.headers[device_idx][sample_idx] = header.replace(param_name + '=' + old_frequency,
                                                             param_name + '=' + "{:.2f}".format(frequency))

        with open(filename, "w") as fw:
            fw.write(self.headers[device_idx][sample_idx])

    # Записать исторические данные в файл
    def write_history_data(self, filename, history_data, device_idx, sample_idx, deb):
        if filename == '':
            device = self.devices_proc[device_idx]
            sample = self.devices_proc[device_idx]["samples"][sample_idx]

            print_log(self.process_num, device["name"], sample["name"], "У файла данных нет заголовочного файла!!!".format(''),
                      Back.RED, self.hfile_logs, deb, self.l)
            return

        with open(filename, mode="ab") as fw:   # Открываем файл для добавления в конец
            for block_idx in range(self.indexes_blocks[device_idx][sample_idx], len(history_data)):
                for idx in range(len(history_data[block_idx].Value.Value)):
                    value = history_data[block_idx].Value.Value[idx]
                    fw.write(struct.pack("<f", value))

    # Удаление устаревших файлов
    def delete_old_files(self, count_pair_files, device_idx, sample_idx, current_datetime, deb):
        device = self.devices_proc[device_idx]
        sample = self.devices_proc[device_idx]["samples"][sample_idx]

        filepath = (device["HomeDir"] + sample["subdir"]).replace("\\", '/')  # Путь к файлам

        count = 0
        for filename in os.listdir(filepath):                                    # Проходимся по списку файлов
            if not (filename.endswith(c_ext_file_header) or filename.endswith(c_ext_file_data)): continue
            if not os.path.exists(filepath + '/' + filename): continue  # Файл удалили на пред. итерации

            if filename.endswith(c_ext_file_header):    # Это заголовочный файл
                str_datetime_created = filename.replace(c_ext_file_header, '')
            else:
                str_datetime_created = filename.replace(c_ext_file_data, '')
            try:
                datetime_created_file = datetime.strptime(str_datetime_created, "%Y_%m_%d_%H%M%S")
            except Exception as e:
                print_log(self.process_num, device["name"], sample["name"], "Не удалось получить дату, время из имени файла '{}' ({})!!!".
                          format(filename, e), Back.RED, self.hfile_logs, deb, self.l)
                break

            if (current_datetime - datetime_created_file).total_seconds() / 86400 <= int(sample["MaxHistoryDays"]): break  # Файл не устарел
            try:
                os.remove(filepath + '/' + filename)
                if filename.endswith(c_ext_file_header):             # Это заголовочный файл
                    filename_ = filename.replace(c_ext_file_header, c_ext_file_data)
                else: filename_ = filename.replace(c_ext_file_data, c_ext_file_header)

                if os.path.exists(filepath + '/' + filename_):
                    os.remove(filepath + '/' + filename_)

                count += 1
                if count >= count_pair_files: break        # Удалили заданное кол-во пар (заголовочный файл, файл данных)
            except Exception as e:
                print_log(self.process_num, device["name"], sample["name"], "Ошибка при удалении устаревшего файла '{}' ({})!!!".
                          format(filename, e), Back.RED, self.hfile_logs, deb, self.l)
                break