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

import os

import marcel.argsparser
import marcel.core
import marcel.exception
import marcel.object.process
import marcel.util


HELP = '''
{L,wrap=F}ps [-u|--user [USER]] [-g|--group [GROUP]] [-p|--pid PID] [-c|--command STRING]

{L,indent=4:28}{r:-u}, {r:--user}              Report only processes owned by the specified USER.

{L,indent=4:28}{r:-g}, {r:--group}             Report only processes owned by the specified GROUP.

{L,indent=4:28}{r:-p}, {r:--pid}               Report only the process with the specified PID.

{L,indent=4:28}{r:-c}, {r:--command}           Report only the processes whose command line contains the specified STRING.

Generate a stream of {n:Process} objects, representing processes. If no arguments are provided,
then all processes, from all users, are reported. Otherwise, the processes are filtered based on the provided
flag.

At most one of the flags can be specified. For more complex selection criteria, run {r:ps} with no
arguments to obtain all {n:Process}es, and then use the {n:select} operator to specify an arbitrary filtering
condition, based on the attributes of {n:Process} objects. (Run {n:help process} for more information on
{n:Process} objects.)

If {r:--user} is specified, and {r:USER} is omitted, then the processes owned by the current user
are provided. Similarly, if {r:--group} is specified and {r:GROUP} is omitted, then the processes
owned by the current user's group are provided.
'''


DETAILS = '''
By default, {r:ps} outputs a {n:Process} object for each process. The flags are all 
concerned with filtering:

{L}{r:--user}: By user.
{L}{r:--group}: By group.
{L}{r:--pid}: By pid.
{L}{r:--command}: By command (select commands containing the given string).

These are conveniences, as arbitrary predicates can be applied by piping {r:ps} output to 
{n:select}.

Run {n:help process} for more information on {n:Process} objects.
'''

_UNINITIALIZED = object()


def ps(env, user=_UNINITIALIZED, group=_UNINITIALIZED, pid=_UNINITIALIZED, command=_UNINITIALIZED):
    op = Ps(env)
    op.user = user
    op.group = group
    op.pid = pid
    op.command = command
    return op


class PsArgsParser(marcel.argsparser.ArgsParser):

    def __init__(self, env):
        super().__init__('ps', env)
        self.add_flag_optional_value('user', '-u', '--user', convert=self.check_str)
        self.add_flag_optional_value('group', '-g', '--group', convert=self.check_str)
        self.add_flag_optional_value('pid', '-p', '--pid', convert=self.check_str)
        self.add_flag_optional_value('command', '-c', '--command', convert=self.check_str)
        self.at_most_one('user', 'group', 'pid', 'command')
        self.validate()


class Ps(marcel.core.Op):

    def __init__(self, env):
        super().__init__(env)
        self.user = _UNINITIALIZED
        self.group = _UNINITIALIZED
        self.pid = _UNINITIALIZED
        self.command = _UNINITIALIZED
        self.filter = None

    # AbstractOp
    
    def setup_1(self):
        self.eval_function('user', int, str)
        self.eval_function('group', int, str)
        self.eval_function('pid', int)
        self.eval_function('command', str)
        # user, group can be name or id. A name can be numeric, and in that case, the name interpretation
        # takes priority. Convert name to uid, since that is a cheaper lookup on a Project.
        # If user or group is None, no user/group was specified, so use this user/group.
        # UNINITIALIZED means it wasn't specified at all.
        #
        # user can be True if -u is specified with no value.
        self.filter = lambda p: True
        if self.user is not _UNINITIALIZED:
            self.user = os.getuid() if self.user in (None, True) else Ps.convert_to_id(self.user, marcel.util.uid)
            self.filter = lambda p: p.uid == self.user
        if self.group is not _UNINITIALIZED:
            self.group = os.getgid() if self.group in (None, True) else Ps.convert_to_id(self.group, marcel.util.gid)
            self.filter = lambda p: p.gid == self.group
        if self.pid is not _UNINITIALIZED:
            try:
                self.pid = int(self.pid)
                self.filter = lambda p: p.pid == self.pid
            except ValueError:
                raise marcel.exception.KillCommandException(f'pid must be an int: {self.pid}')
        if self.command is not _UNINITIALIZED:
            self.filter = lambda p: self.command in p.commandline

    def receive(self, _):
        for process in marcel.object.process.processes():
            if self.filter(process):
                self.send(process)

    # Op

    def must_be_first_in_pipeline(self):
        return True

    # For use by this class

    @staticmethod
    def convert_to_id(name, lookup):
        id = lookup(name)
        if id is None:
            try:
                id = int(name)
            except ValueError:
                pass
        if id is None:
            raise marcel.exception.KillCommandException(f'{name} is not a recognized id or name.')
        return id

