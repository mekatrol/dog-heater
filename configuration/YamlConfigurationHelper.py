import os.path
import yaml


class YamlConfigurationHelper:

    def __init__(self, file_name, debug_file_name):
        self.file_name = file_name
        self.debug_file_name = debug_file_name

        # Create empty dictionary for config
        self._config = {}

    @property
    def Config(self):
        return self._config

    async def read(self):
        # Load the config file
        with open(self.file_name) as f:
            self._config = yaml.load(f, Loader=yaml.FullLoader)

        # If a debug config file exits then load it
        if os.path.isfile(self.debug_file_name):
            with open(self.debug_file_name) as f:
                cfg_debug = yaml.load(f, Loader=yaml.FullLoader)

            # Override config settings with any settings found in the debug config
            for key in cfg_debug.keys():
                for sub_key in cfg_debug[key]:
                    self._config[key].update({sub_key: cfg_debug[key][sub_key]})

        return self._config