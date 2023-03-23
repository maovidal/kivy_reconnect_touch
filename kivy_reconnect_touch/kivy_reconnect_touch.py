""" ----------------------------------------------------------------------------

This is a rudimentary effort to implement a touch screen reconnect in Kivy.
It is meant for Linux and uses Trio.

It works by monitoring the changes on the folder where Linux exposes the
devices that work as inputs:

- If the content is reduced, this script assumes there is a disconnection
  of the touch device.
- If the content is increased, this script assumes there is a connection
  of the touch device.

However it has the following limitations:

- It works only for one specific device set on Kivy's configuration file.
- Monitoring the folder content may triggered the updates for causes that
  may not be related to the touch.
- If the consecutive content of the monitored folder changes faster than the
  periodic sampling, the update won't be triggered.


Setup:

1. Kivy `config.ini` should have the device configured with something like this
(The tested touch device in my case is a eGalax touch screen that requires
inversion of its axis):

```
[input]
mouse = mouse
egalaxP829_9AHDT = probesysfs,match=eGalax Inc. Touch Touchscreen,select_all=1,provider=hidinput,param=invert_x=1,param=invert_y=0
```

2. Make sure the expected Kivy's config.ini is used. That can be achieved
using the environment variable KIVY_HOME:

```
export KIVY_HOME=/path/to/your/config/file
```

3. Be sure to set the same name of the device on `TOUCH_DEVICE_NAME`. The
variable `FOLDER_TO_MONITOR` is set to monitor the changes of the folder
'/sys/class/input' in Linux.

4. Once running this script, disconnect or connect the cable of the touch
device. Kivy's interface and log should provide information about it is
dealing with the available input devices.

---------------------------------------------------------------------------- """

import os
from glob import glob
from enum import Enum
import trio

from kivy.logger import (
    Logger,
)
from kivy.lang import (
    Builder,
)
from kivy.app import (
    App,
)
from kivy.base import (
    EventLoop,
)
from kivy.input.providers.probesysfs import(
    ProbeSysfsHardwareProbe,
)
from kivy.properties import (
    StringProperty,
)


# Touch device name
TOUCH_DEVICE_NAME = 'egalaxP829_9AHDT'

# The folder that changes when an input device connected/disconnected in Linux
FOLDER_TO_MONITOR = '/sys/class/input'


class MonitoredEvent(Enum):
    """
    Identifies the event monitored.
    """
    NO_CHANGE = 0
    CONNECTED = 1
    DISCONNECTED = 2


class TouchReconnect(App):
    """
    This is the Kivy App.
    """
    def __init__(self, **kwargs):
        """
        Includes Trio support.
        """
        super().__init__(**kwargs)
        Logger.info("TouchReconnect app initializing")
        # Trio nursery
        self.nursery = None
        # A cache of the folder to monitor is kept. Its initial content is
        # loaded here, at start
        self._cache_input: list = self._monitored_folder_content()

    # Variable to decide when an input rebuild is necessary
    events_recorded = StringProperty('The events will appear here once the touch cable is connected or disconnected')

    def _monitored_folder_content(self) -> list:
        """
        Returns the content of the monitored folder.
        """
        event_glob = os.path.join(FOLDER_TO_MONITOR, "event*")
        got = [x for x in glob(event_glob)]
        return got

    def _get_change_in_monitored_folder(self) -> MonitoredEvent:
        """
        Returns a class `MonitoredEvent` indicating the event on the monitored
        folder.
        """

        # Updates the current content of the monitored folder
        current_cache_input = self._monitored_folder_content()

        # If the current content is different from the previous, then we
        # report that.
        if self._cache_input == current_cache_input:
            return MonitoredEvent.NO_CHANGE
        else:
            if len(self._cache_input) < len(current_cache_input):
                self._cache_input = current_cache_input
                return MonitoredEvent.CONNECTED
            else:
                self._cache_input = current_cache_input
                return MonitoredEvent.DISCONNECTED

    async def reconnect_cycle(self):
        """
        Routinely checks if a reconnect is asked, and performs it if required.
        """
        try:
            # The next is a reference of the EventLoop, which is a singleton
            # that contains a list of the input devices
            the_event_loop = EventLoop

            while True:
                # Checks for a change on the connection
                change_in_monitored_folder = self._get_change_in_monitored_folder()
                if change_in_monitored_folder is MonitoredEvent.CONNECTED:
                    Logger.info('Heads up, a connection has happened')
                    self.events_recorded = self.events_recorded + '\nHeads up, a connection has occurred'

                elif change_in_monitored_folder is MonitoredEvent.DISCONNECTED:
                    Logger.info('Heads up, a disconnection has happened')
                    self.events_recorded = self.events_recorded + '\nHeads up, a disconnection has occurred'

                if change_in_monitored_folder is not MonitoredEvent.NO_CHANGE:
                    # We inform about the current input providers available
                    got_device_names = ''
                    for provider in the_event_loop.input_providers:
                        got_device_names = got_device_names + '\n' + str(provider.device)
                    Logger.info(f'These are the current providers available: {got_device_names}')

                    # When a device has been disconnected
                    if change_in_monitored_folder is MonitoredEvent.DISCONNECTED:
                        # We remove it from the available input providers...
                        # (Based on: https://github.com/kivy/kivy/blob/c28c47b39ae57c97c70cc0398d74774d73a6894b/kivy/base.py#L193)
                        for provider in the_event_loop.input_providers:
                            # ... only if the device name matches the expected
                            if str(provider.device).lower() == str(TOUCH_DEVICE_NAME).lower():
                                provider.stop()
                                the_event_loop.remove_input_provider(provider)
                                Logger.info(f'{provider.device} has been stopped and removed')

                    # When a device has been connected
                    if change_in_monitored_folder is MonitoredEvent.CONNECTED:
                        # We ask Probesysfs to work its magic to add the provider
                        ProbeSysfsHardwareProbe(device=str(TOUCH_DEVICE_NAME).lower(), args='match=eGalax Inc. Touch Touchscreen,select_all=1,provider=hidinput,param=invert_x=1,param=invert_y=0')
                        # And now we start it
                        for provider in the_event_loop.input_providers:
                            if str(provider.device).lower() == str(TOUCH_DEVICE_NAME).lower():
                                provider.start()
                                Logger.info(f'{str(provider.device)} has been asked to start')

                    # Checks for the resulting providers
                    got_device_names = ''
                    for provider in the_event_loop.input_providers:
                        got_device_names = got_device_names + '\n' + str(provider.device)
                    Logger.info(f'After the connection/disconnection, these are the providers available: {got_device_names}')

                # Performs the check every second
                await trio.sleep(1.0)

        except trio.Cancelled as exception:
            Logger.info(f'Reconnect cycle was canceled: {exception}')
        finally:
            Logger.info('Reconnect cycle has been done')

    def build(self):
        """
        Provides the root object.
        """
        return Builder.load_file('kivy_reconnect_touch.kv')

    async def app_func(self):
        """
        Trio needs to run a function, so this is it.
        """
        async with trio.open_nursery() as nursery:
            # In Trio you create a nursery, in which you schedule async
            # functions to be run by the nursery simultaneously as tasks.

            # This will run all two methods starting in random order
            # asynchronously and then block until they are finished or canceled
            # at the `with` level.
            self.nursery = nursery

            async def run_wrapper():
                # Trio needs to be set so that it'll be used for the event loop
                await self.async_run(async_lib='trio')
                Logger.info('Kivy App done')
                nursery.cancel_scope.cancel()

            nursery.start_soon(run_wrapper)
            nursery.start_soon(self.reconnect_cycle)


if __name__ == "__main__":

    # Clears the terminal
    print("\033c")

    trio.run(TouchReconnect().app_func)
