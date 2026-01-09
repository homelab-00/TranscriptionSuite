import pyaudio

p = pyaudio.PyAudio()
info = p.get_host_api_info_by_index(0)
numdevices = info.get("deviceCount", 0)
if isinstance(numdevices, str):
    numdevices = int(numdevices)

print("Available Audio Input Devices:\n")

for i in range(0, numdevices):
    device_info = p.get_device_info_by_host_api_device_index(0, i)
    max_input_channels = device_info.get("maxInputChannels", 0)
    if isinstance(max_input_channels, (int, float)) and max_input_channels > 0:
        print(f'  Index: {device_info.get("index")}, Name: "{device_info.get("name")}"')

print(
    "\nFind the device you want to use and put its 'Index' into the config.json file."
)
