# Original work Copyright Fabio Zadrozny (EPL 1.0)
# See ThirdPartyNotices.txt in the project root for license information.
# All modifications Copyright (c) Robocorp Technologies Inc.
# All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http: // www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys

import pytest
import logging
from robocorp_ls_core.unittest_tools.monitor import dump_threads

log = logging.getLogger(__name__)


_started_monitoring_threads = False


def _start_monitoring_threads():
    # After the session finishes, wait 20 seconds to see if everything finished properly
    # and if it doesn't report an error.
    global _started_monitoring_threads
    if _started_monitoring_threads:
        return

    _started_monitoring_threads = True
    import threading

    if hasattr(sys, "_current_frames") and hasattr(threading, "enumerate"):
        import time

        class DumpThreads(threading.Thread):
            def run(self):

                time.sleep(20)
                dump_threads()

                # Force thread run to finish
                import os

                os._exit(123)

        dump_current_frames_thread = DumpThreads()
        # Daemon so that this thread doesn't halt it!
        dump_current_frames_thread.daemon = True
        dump_current_frames_thread.start()


@pytest.hookimpl
def pytest_unconfigure():
    _start_monitoring_threads()


@pytest.hookimpl
def pytest_configure(config):
    import os
    from robocorp_ls_core.options import USE_TIMEOUTS

    if not USE_TIMEOUTS:
        os.environ["PYTEST_TIMEOUT"] = "999999"


@pytest.fixture(scope="session", autouse=True)
def check_no_threads():
    yield
    _start_monitoring_threads()


# see: http://goo.gl/kTQMs
SYMBOLS = {
    "customary": ("B", "K", "M", "G", "T", "P", "E", "Z", "Y"),
    "customary_ext": (
        "byte",
        "kilo",
        "mega",
        "giga",
        "tera",
        "peta",
        "exa",
        "zetta",
        "iotta",
    ),
    "iec": ("Bi", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi", "Yi"),
    "iec_ext": ("byte", "kibi", "mebi", "gibi", "tebi", "pebi", "exbi", "zebi", "yobi"),
}


def bytes2human(n, format="%(value).1f %(symbol)s", symbols="customary"):
    """
    Bytes-to-human / human-to-bytes converter.
    Based on: http://goo.gl/kTQMs
    Working with Python 2.x and 3.x.

    Author: Giampaolo Rodola' <g.rodola [AT] gmail [DOT] com>
    License: MIT
    """

    """
    Convert n bytes into a human readable string based on format.
    symbols can be either "customary", "customary_ext", "iec" or "iec_ext",
    see: http://goo.gl/kTQMs

      >>> bytes2human(0)
      '0.0 B'
      >>> bytes2human(0.9)
      '0.0 B'
      >>> bytes2human(1)
      '1.0 B'
      >>> bytes2human(1.9)
      '1.0 B'
      >>> bytes2human(1024)
      '1.0 K'
      >>> bytes2human(1048576)
      '1.0 M'
      >>> bytes2human(1099511627776127398123789121)
      '909.5 Y'

      >>> bytes2human(9856, symbols="customary")
      '9.6 K'
      >>> bytes2human(9856, symbols="customary_ext")
      '9.6 kilo'
      >>> bytes2human(9856, symbols="iec")
      '9.6 Ki'
      >>> bytes2human(9856, symbols="iec_ext")
      '9.6 kibi'

      >>> bytes2human(10000, "%(value).1f %(symbol)s/sec")
      '9.8 K/sec'

      >>> # precision can be adjusted by playing with %f operator
      >>> bytes2human(10000, format="%(value).5f %(symbol)s")
      '9.76562 K'
    """
    n = int(n)
    if n < 0:
        raise ValueError("n < 0")
    symbols = SYMBOLS[symbols]
    prefix = {}
    for i, s in enumerate(symbols[1:]):
        prefix[s] = 1 << (i + 1) * 10
    for symbol in reversed(symbols[1:]):
        if n >= prefix[symbol]:
            value = float(n) / prefix[symbol]
            return format % locals()
    return format % dict(symbol=symbols[0], value=n)


def format_memory_info(memory_info, curr_proc_memory_info):
    return "Total: %s, Available: %s, Used: %s %%, Curr process: %s" % (
        bytes2human(memory_info.total),
        bytes2human(memory_info.available),
        memory_info.percent,
        format_process_memory_info(curr_proc_memory_info),
    )


def format_process_memory_info(proc_memory_info):
    return bytes2human(proc_memory_info.rss)


DEBUG_MEMORY_INFO = False

_global_collect_info = False


@pytest.fixture(autouse=False)
def before_after_each_function(request):
    global _global_collect_info

    try:
        import psutil  # Don't fail if not there
    except ImportError:
        yield
        return

    current_pids = set(proc.pid for proc in psutil.process_iter())
    before_curr_proc_memory_info = psutil.Process().memory_info()

    if _global_collect_info and DEBUG_MEMORY_INFO:
        try:
            from pympler import summary, muppy

            sum1 = summary.summarize(muppy.get_objects())
        except:
            log.exception()

    sys.stdout.write(
        """
===============================================================================
Memory before: %s
%s
===============================================================================
"""
        % (
            request.function,
            format_memory_info(psutil.virtual_memory(), before_curr_proc_memory_info),
        )
    )
    yield

    processes_info = []
    for proc in psutil.process_iter():
        if proc.pid not in current_pids:
            try:
                try:
                    cmdline = proc.cmdline()
                except:
                    cmdline = "<unable to get>"
                processes_info.append(
                    "New Process: %s(%s - %s) - %s"
                    % (
                        proc.name(),
                        proc.pid,
                        cmdline,
                        format_process_memory_info(proc.memory_info()),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # The process could've died in the meanwhile

    after_curr_proc_memory_info = psutil.Process().memory_info()

    if DEBUG_MEMORY_INFO:
        try:
            if (
                after_curr_proc_memory_info.rss - before_curr_proc_memory_info.rss
                > 10 * 1000 * 1000
            ):
                # 10 MB leak
                if _global_collect_info:
                    sum2 = summary.summarize(muppy.get_objects())
                    diff = summary.get_diff(sum1, sum2)
                    sys.stdout.write(
                        "===============================================================================\n"
                    )
                    sys.stdout.write("Leak info:\n")
                    sys.stdout.write(
                        "===============================================================================\n"
                    )
                    summary.print_(diff)
                    sys.stdout.write(
                        "===============================================================================\n"
                    )

                _global_collect_info = True
                # We'll only really collect the info on the next test (i.e.: if at one test
                # we used too much memory, the next one will start collecting)
            else:
                _global_collect_info = False
        except:
            log.exception()

    sys.stdout.write(
        """
===============================================================================
Memory after: %s
%s%s
===============================================================================


"""
        % (
            request.function,
            format_memory_info(psutil.virtual_memory(), after_curr_proc_memory_info),
            ""
            if not processes_info
            else "\nLeaked processes:\n" + "\n".join(processes_info),
        )
    )
