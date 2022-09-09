""" ----------------------------------------------------------------------------

**THIS IS A WORK IN PROGRESS**

This is an effort to implement a touch screen reconnect in Kivy.
It is meant for Linux and use Trio.

Setup:

1. Kivy `config.ini` should have the device configured with something like this
(The tested touch device in my case is a eGalax touch screen that requires
inversion of its surface):

```
[input]
mouse = mouse
egalaxP829_9AHDT = probesysfs,match=eGalax Inc. Touch Touchscreen,select_all=1,provider=hidinput,param=invert_x=1,param=invert_y=0
```

2. Make sure the expected Kivy's config.ini is used. That can be achieve
using the environment variable KIVY_HOME:

```
export KIVY_HOME=/path/to/your/config/file
```

3. Be sure to set the same name of the device on `TOUCH_DEVICE_NAME`. The
variable `FOLDER_TO_MONITOR` is set to monitor the changes of the folder
'/sys/class/input' in Linux.

4. There is an additional handler configured here for the logger. If not used,
please comment it to disable it.

5. Once running this script, pulse the button. Kivy's log should provide
information about how it removes the input provider and later, how it
adds it back.
---------------------------------------------------------------------------- """


import logging.handlers
import os
from glob import glob
import trio

from kivy.config import (
    Config,
)
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
from kivy.input import(
    MotionEventFactory,
)
from kivy.properties import (
    BooleanProperty,
)


# Touch device name
TOUCH_DEVICE_NAME = 'egalaxP829_9AHDT'
# The folder that changes when an input device is changed in Linux
FOLDER_TO_MONITOR = '/sys/class/input'


# The next is not required. It just provide the log output to an external
# Syslog server, which in my case helps to debug the embedded device that
# runs this code.

# Comment if not required.
handler = logging.handlers.SysLogHandler(
    address=('192.168.2.1', 5514),
    facility=19,
)
Logger.addHandler(handler)


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
    ask_for_inputs_rebuild = BooleanProperty(False)

    def _monitored_folder_content(self) -> list:
        """
        Returns the content of the monitored folder.
        """
        event_glob = os.path.join(FOLDER_TO_MONITOR, "event*")
        got = [x for x in glob(event_glob)]
        # Logger.info(f"The current content is: {got}")
        return got

    def _changed_monitored_folder(self) -> bool:
        """
        Returns:
        - True, if the monitored folder have had changes on its content.
        - False, otherwise
        """

        # Updates the current content of the monitored folder
        current_cache_input = self._monitored_folder_content()

        # If the current content is different from the previous, then we
        # report that.
        if self._cache_input:
            if self._cache_input == current_cache_input:
                return False
        # Reaching this point means the cache has changed
        self._cache_input = current_cache_input
        return True

    async def reconnect_cycle(self):
        """
        Routinely checks if a reconnect is asked, and performs it if required.
        """
        try:
            # The next is a reference of the EventLoop, which is a singleton
            # that contains a list of the input devices
            the_event_loop = EventLoop

            while True:
                has_monitored_folder_changed = self._changed_monitored_folder()
                if has_monitored_folder_changed is True:
                    Logger.info('Heads up, the monitored folder has changed')

                # if self.ask_for_inputs_rebuild is True:
                if has_monitored_folder_changed is True or self.ask_for_inputs_rebuild is True:
                    # We inform about the current input providers available
                    got_device_names = ''
                    for provider in the_event_loop.input_providers:
                        got_device_names = got_device_names + '\n' + str(provider.device)
                    Logger.info(f'Prior removing providers we have this available: {got_device_names}')

                    # Now we perform the removal...
                    # (Based on: https://github.com/kivy/kivy/blob/c28c47b39ae57c97c70cc0398d74774d73a6894b/kivy/base.py#L193)
                    for provider in reversed(EventLoop.input_providers[:]):
                        # ... only if the device name matches the expected
                        if str(provider.device).lower() == str(TOUCH_DEVICE_NAME).lower():
                            Logger.info(f'{provider.device} will be removed')
                            provider.stop()
                            EventLoop.remove_input_provider(provider)
                        else:
                            Logger.info(f'{provider.device} will be kept')

                    # Checks for the removal
                    await trio.sleep(1.0)
                    got_device_names = ''
                    for provider in the_event_loop.input_providers:
                        got_device_names = got_device_names + '\n' + str(provider.device)
                    Logger.info(f'After removing we have this available: {got_device_names}')

                    # Asks to append the input device again
                    # We will look for the device details from the current
                    # configuration.
                    # (Based on: https://github.com/kivy/kivy/blob/c28c47b39ae57c97c70cc0398d74774d73a6894b/kivy/base.py#L498)
                    for key, value in Config.items('input'):
                        if str(key).lower() == str(TOUCH_DEVICE_NAME).lower():
                            Logger.info('Base: Create provider from %s' % (str(value)))

                            # split value
                            args = str(value).split(',', 1)
                            if len(args) == 1:
                                args.append('')
                            provider_id, args = args
                            provider = MotionEventFactory.get(provider_id)
                            if provider is None:
                                Logger.warning('Base: Unknown <%s> provider' % str(provider_id))
                                continue

                            # create provider
                            p = provider(key, args)
                            if p:
                                EventLoop.add_input_provider(p, True)

                    # Is is necessary?
                    the_event_loop.start()

                    # Checks that the inclusion was performed
                    await trio.sleep(1.0)
                    got_device_names = ''
                    for provider in the_event_loop.input_providers:
                        got_device_names = got_device_names + '\n' + str(provider.device)
                    Logger.info(f'After inclusion we have this available: {got_device_names}')

                    # Sets the flag to its default value
                    self.ask_for_inputs_rebuild = False

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
