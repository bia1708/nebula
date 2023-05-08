import glob
import logging
import os
import pathlib

import click
import nebula.errors as ne
import netifaces
import yaml
from nebula.common import multi_device_check
from nebula.netbox import NetboxDevice, NetboxDevices, netbox

LINUX_DEFAULT_PATH = "/etc/default/nebula"
WINDOWS_DEFAULT_PATH = "C:\\nebula\\nebula.yaml"

log = logging.getLogger(__name__)


def convert_by_id_to_tty(by_id):
    """Translate frandom:
    /dev/serial/by-id/usb-Silicon_Labs_CP2103_USB_to_UART_Bridge_Controller_0001-if00-port0
    to
    /dev/ttyUSB1
    """
    import pyudev

    context = pyudev.Context()
    for device in context.list_devices(subsystem="tty", ID_BUS="usb"):
        if by_id in device.device_links:
            return device.device_node
    return False


def convert_address_to_tty(address):
    """Translate frandom:
    /dev/serial/by-id/usb-Silicon_Labs_CP2103_USB_to_UART_Bridge_Controller_0001-if00-port0
    to
    /dev/ttyUSB1
    Will also work with by_path. Works in docker container.
    """
    import pyudev

    context = pyudev.Context()
    tty = pyudev.Devices.from_device_file(context, address)
    if tty:
        return tty.get("DEVNAME")
    else:
        return False


def get_uarts():
    strs = "\n(Found: "
    default = None
    if os.name in ["nt", "posix"]:
        LINUX_SERIAL_FOLDER = "/dev/serial"
        if os.path.isdir(LINUX_SERIAL_FOLDER):
            fds = glob.glob(LINUX_SERIAL_FOLDER + "/by-id/*")
            for fd in fds:
                print(fd)
                strs = strs + "\n" + str(fd)
                default = str(fd)
            strs = strs[:-2] + ") "
            return (strs, default)
    return (None, default)


def get_nics():
    filter = ["docker0", "lo"]
    default = None
    str = "\n(Found: "
    for nic in netifaces.interfaces():
        if nic not in filter:
            str = str + nic + ", "
            default = nic
    str = str[:-2] + ") "
    return (str, default)


class helper:
    def __init__(self):
        pass

    def list_supported_boards(self, filter=None):
        path = pathlib.Path(__file__).parent.absolute()
        res = os.path.join(path, "resources", "board_table.yaml")
        with open(res) as f:
            board_configs = yaml.load(f, Loader=yaml.FullLoader)
        for config in board_configs:
            if filter in config or not filter:
                print(config)

    def update_yaml(  # noqa: C901
        self, configfilename, section, field, new_value, board_name=None
    ):
        """Update single field of exist config file"""

        if not os.path.isfile(configfilename):
            raise Exception("Specified yaml file does not exist")
        with open(configfilename, "r") as stream:
            configs = yaml.safe_load(stream)
        board_name_request = field == "board-name" and section == "board-config"

        try:
            cfg = multi_device_check(configs, board_name)
        except ne.MultiDevFound:
            if not board_name_request:
                raise ne.MultiDevFound
            # Print out list of boards
            ks = configs.keys()
            names = []
            for config in ks:
                for cfg in configs[config]:
                    if cfg == "board-config":
                        for c in configs[config][cfg]:
                            for f in c:
                                if f == "board-name":
                                    names.append(c["board-name"])
            print(", ".join(names))
            return
        configs = cfg

        updated = False
        try:
            for i, f in enumerate(configs[section]):
                if field in list(f.keys()):
                    updated = True
                    value = configs[section][i][field]
                    if new_value:
                        configs[section][i][field] = new_value
                        print(
                            "Field",
                            field,
                            "in",
                            section,
                            "updated from",
                            value,
                            "to",
                            new_value,
                        )
                    else:
                        # Handle serial translation
                        if section == "uart-config" and field == "address":
                            value = convert_address_to_tty(value)
                        print(str(value))
                    log.info(field + ": " + str(value))
                    break
            if not updated:
                raise Exception("")
        except Exception:
            raise Exception("Field or section does not exist")
        if new_value:
            self._write_config_file(configfilename, configs)

    def create_config_interactive(self):  # noqa: C901
        # Read in template
        path = pathlib.Path(__file__).parent.absolute()
        res = os.path.join(path, "resources", "template_gen.yaml")
        stream = open(res, "r")
        configs = yaml.safe_load(stream)
        stream.close()
        outconfig = dict()
        required_sections = []
        print("YAML Config Interactive Generation")
        print("###################")
        print("FYI Questions are arranged:")
        print("  Question (Options) [Default]")
        print("###################")
        for key in configs.keys():
            # Ask if we need it
            if key not in required_sections:
                s = "Do you want to setup " + key + " [Y/n] : "
                o = input(s)
                if o == "n":
                    continue
            #
            section = configs[key]
            outconfig[key] = []
            current_depends = None
            required_answer = None
            for fields in section.keys():
                field = section[fields]
                while 1:
                    # Get dependent props
                    if "requires" in list(field.keys()):
                        deps_string = field["requires"].split(":")
                        required_answer = deps_string[0]
                        current_depends = deps_string[1].split(",")

                    # Filter out if not needed
                    if isinstance(field["optional"], str):
                        # print("optional", field["optional"], field["name"])
                        # print("current_depends", current_depends)
                        if not current_depends:
                            break  # Skip
                        if field["name"] not in current_depends:
                            break  # Skip

                    # Form question
                    # stri = field["help"] + ".\nExample: " + str(field["default"]) + " "
                    # if field["optional"] == True:
                    #     stri = stri + " (optional)"
                    # if "callback" in list(field.keys()):
                    #     out = eval(field["callback"] + "()")
                    #     if out:
                    #         stri = stri + out
                    # stri = stri + ": "
                    # print("-------------")
                    # out = input(stri)

                    extend = ""
                    if "default" in list(field.keys()):
                        default = field["default"]
                    else:
                        default = None
                    ################
                    if "callback" in list(field.keys()):
                        (out, defaultcb) = eval(field["callback"] + "()")
                        if out:
                            extend = out
                        if defaultcb:
                            default = defaultcb

                    ################
                    if "options" in field.keys():
                        options = field["options"]
                        options = click.Choice(options)
                    else:
                        options = None
                    print("###################")
                    out = click.prompt(
                        text=click.style(field["help"] + extend, fg="green"),
                        prompt_suffix=": ",
                        default=default,
                        type=options,
                        show_choices=True,
                    )
                    ################
                    # Check if meets required answers for dependent properties checks to be enabled
                    if required_answer:
                        if not required_answer == out:  # Disable dependency check
                            current_depends = None
                    required_answer = None  # Reset so we break while

                    # Check if we need to ask again
                    if not out:
                        if (not field["optional"]) or (
                            field["name"] in current_depends
                        ):
                            # print("Not optional!!!!")
                            continue
                        break  # Skip
                    # Convert string to boolean
                    if isinstance(out, str):
                        if out.lower() == "false":
                            out = False
                        elif out.lower() == "true":
                            out = True
                    d = {field["name"]: out}
                    outconfig[key].append(d)
                    break
        # Output
        if os.name == "nt" or os.name == "posix":
            if os.path.exists(LINUX_DEFAULT_PATH):
                NEB_PATH = LINUX_DEFAULT_PATH
            else:
                NEB_PATH = WINDOWS_DEFAULT_PATH

        loc = input(
            "Output config file (this not just a folder) [{}] : ".format(NEB_PATH)
        )
        if not loc:
            loc = NEB_PATH
        self._write_config_file(loc, outconfig)
        # out = os.path.join(head_tail[0], "resources", "out.yaml")
        print("Pew pew... all set")

    def create_config_from_netbox(
        self,
        outfile="nebula",
        netbox_ip="localhost",
        netbox_port=None,
        netbox_baseurl=None,
        netbox_token=None,
        jenkins_agent=None,
        board_name=None,
        include_variants=None,
        include_children=None,
        devices_status=None,
        devices_role=None,
        devices_tag=None,
        template=None,
    ):
        # Read in template
        path = pathlib.Path(__file__).parent.absolute()
        template = os.path.join(
            path, "resources", template if template else "template_gen.yaml"
        )
        ni = netbox(
            ip=netbox_ip,
            port=netbox_port,
            base_url=netbox_baseurl,
            token=netbox_token,
            load_config=False,
        )
        outconfig = dict()
        config = dict()

        # load config from file
        with open(template, "r") as f:
            config = yaml.safe_load(f)

        if board_name:
            nbd = NetboxDevice(ni, device_name=board_name)
            outconfig = nbd.to_config(config)
        else:
            nbds = NetboxDevices(
                ni,
                variants=include_variants,
                children=include_children,
                status=devices_status,
                role=devices_role,
                agent=jenkins_agent,
                tag=devices_tag,
            )
            outconfig = nbds.generate_config(config)

        self._write_config_file(filename=outfile, outconfig=outconfig)

    def _write_config_file(self, filename, outconfig):
        with open(filename, "w") as file:
            yaml.dump(outconfig, file, default_flow_style=False)

        # Post process to fix yaml.dump bug where boolean are all lowercase
        file1 = open(filename, "r")
        lines = []
        for line in file1.readlines():
            line = line.replace(": true\n", ": True\n")
            line = line.replace(": false\n", ": False\n")
            lines.append(line)
        file1.close()
        file1 = open(filename, "w")
        file1.writelines(lines)
        file1.close()
