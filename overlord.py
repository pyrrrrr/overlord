from lib.configLoader import loadConfigDir
from lib.app import MonitorApp
from lib.pluginLoader import PluginRegistry

pluginRegistry = PluginRegistry()
pluginRegistry.loadPluginsFromPackage("plugins")

config = loadConfigDir("configs", pluginRegistry=pluginRegistry)

app = MonitorApp(config, pluginPackage="plugins")
app.run()