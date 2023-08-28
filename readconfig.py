import xml.etree.ElementTree as ET


# Возвращает список устройств (контроллеров), распределенные по разным процессам
def get_devices_processes(filename, debug=False):
    try:
        tree = ET.parse(filename)
        root = tree.getroot()

        devices = []  # Список устройств (контроллеры)

        for child in root:
            devices.append(child.attrib)

            devices[-1]["samples"] = []

            for sub_child in child:
                devices[-1]["samples"].append(sub_child.attrib)

        devices_processes = []  # Устройства, распределенные по процессам

        for process_num in range(1, 17):
            devices_processes.append(
                [])  # Создаем список для добавления в него устройств, обрабатываемых процессом с номером process_num

            for device in devices:
                device_proc = {}  # Устройство, обрабатываемое в процессе с номером process_num
                for key in list(device.keys()):
                    if key == "samples":
                        device_proc[key] = []
                    else:
                        device_proc[key] = device[key]

                for sample in device["samples"]:
                    if int(sample["process"]) == process_num:  # Выборка обрабатывается в процессе с номером process_num
                        device_proc["samples"].append(sample)
                if len(device_proc["samples"]) != 0: devices_processes[-1].append(device_proc)
        if debug:
            for process_idx, devices in enumerate(devices_processes):
                if len(devices) == 0: break
                print("Process {}:".format(process_idx + 1))
                print(devices)

        return devices_processes
    except  Exception as err:
        print("Error parse config file '{}' ({})!!!".format(filename, err))
        return []


if __name__ == '__main__':
    devices_processes = get_devices_processes("config.xml", debug=True)

    print(len(devices_processes))