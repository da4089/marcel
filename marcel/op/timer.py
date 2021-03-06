# This file is part of Marcel.
# 
# Marcel is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or at your
# option) any later version.
# 
# Marcel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Marcel.  If not, see <https://www.gnu.org/licenses/>.

import marcel.argsparser
import marcel.core
import marcel.exception

import threading
import time


HELP = '''
{L,wrap=F}timer [-c|--components] INTERVAL

{L,indent=4:28}{r:-c}, {r:--components}        Output timestamp as a Python {n:time.struct_time} value, instead of seconds.

{L,indent=4:28}{r:INTERVAL}                The amount of time to wait between consecutive timestamps.

Generate a sequence of timestamps, separated in time by a specified {r:INTERVAL}.

The {r:INTERVAL} format is {n:HH:MM:SS} where {r:HH} is hours, 
{r:MM} is minutes, {r:SS} is seconds. {r:HH:} and
{r:HH:MM:} may be omitted.

{b:Examples}:
{p,wrap=F}
    {r:interval}        meaning
    ------------------------------------
    5               5 seconds
    1:30            1 minute, 30 seconds
    1:00:00         1 hour

By default, the output timestamp is time in seconds since 1/1/1970.
If {r:-c} is specified, then the timestamp is rendered as a Python {n:time.struct_time}
tuple: (year, month, day, hour, minute, second, weekday, day of year, daylight savings time flag).

Notes:
{L}- month is 1-based (January = 1, February = 2, ...)
{L}- day of month is 1-based.
{L}- second can go as high as 61 due to leap-seconds.
{L}- day of week is 0-based, Monday = 0.
{L}- day of year is 1-based.
{L}- dst is 1 if Daylight Savings Time is in effect, 0 otherwise.
'''


def timer(env, interval, components=False):
    args = ['--components'] if components else []
    args.append(interval)
    return Timer(env), args


class TimerArgsParser(marcel.argsparser.ArgsParser):

    def __init__(self, env):
        super().__init__('timer', env)
        self.add_flag_no_value('components', '-c', '--components')
        self.add_anon('interval', convert=self.check_str)
        self.validate()


class Timer(marcel.core.Op):

    def __init__(self, env):
        super().__init__(env)
        self.components = None
        self.metronome = None
        self.interval = None
        self.lock = None
        self.done = False
        self.now = None

    def __repr__(self):
        return f'timer({self.interval})'

    # AbstractOp
    
    def setup_1(self):
        self.lock = threading.Condition()
        self.interval = self.parse_interval(self.interval)
        self.metronome = Metronome(self)

    # AbstractOp
    
    def receive(self, _):
        # Timer events are generated by the metronome class, which is a separate
        # thread. This keeps the intervals close to what is specified. If the
        # timer is run in the current thread, then the interval would control
        # the time between completion of downstream computing (invoked by self.send)
        # and the next timer event.
        self.metronome.start()
        while not self.done:
            self.lock.acquire()
            while self.now is None:
                # If the timeout is omitted from the wait call, then ctrl-c
                # cannot interrupt. The threading module implements wait
                # differently if a timeout is specified, waking up periodically.
                # TODO: Still true?
                self.lock.wait(1.0)
            now = self.now
            if not self.components:
                now = time.mktime(now)
            self.now = None
            self.lock.release()
            self.send(now)

    # Op

    def must_be_first_in_pipeline(self):
        return True

    # For use by this module

    @staticmethod
    def parse_interval(interval):
        try:
            colon1 = interval.find(':')
            colon2 = -1
            if colon1 > 0:
                colon2 = interval.find(':', colon1 + 1)
            # Normalize
            if colon1 < 0:
                # No colons
                interval = '0:0:' + interval
            elif colon2 < 0:
                # One colon
                interval = '0:' + interval
            colon1 = interval.find(':')
            colon2 = interval.find(':', colon1 + 1)
            hh = int(interval[:colon1])
            mm = int(interval[colon1 + 1:colon2])
            ss = int(interval[colon2 + 1:])
            return hh * 3600 + mm * 60 + ss
        except Exception as e:
            raise marcel.exception.KillCommandException(f'Bad interval format: {e}')

    def register_tick(self):
        self.lock.acquire()
        self.now = time.localtime()
        self.lock.notifyAll()
        self.lock.release()


class Metronome(threading.Thread):

    def __init__(self, op):
        threading.Thread.__init__(self)
        self.interval = op.interval
        self.timer = op
        self.setDaemon(True)

    def run(self):
        while True:
            self.timer.register_tick()
            time.sleep(self.interval)
