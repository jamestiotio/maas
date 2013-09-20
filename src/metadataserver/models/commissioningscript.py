# Copyright 2012, 2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Custom commissioning scripts, and their database backing."""


from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

__metaclass__ = type
__all__ = [
    'BUILTIN_COMMISSIONING_SCRIPTS',
    'CommissioningScript',
    'LLDP_OUTPUT_NAME',
    'LSHW_OUTPUT_NAME',
    ]

from functools import partial
from inspect import getsource
from io import BytesIO
from itertools import chain
import json
import os.path
import tarfile
from textwrap import dedent
from time import time as now

from django.db.models import (
    CharField,
    Manager,
    Model,
    )
from lxml import etree
from maasserver.fields import MAC
from maasserver.models.tag import Tag
from metadataserver import DefaultMeta
from metadataserver.fields import BinaryField

# Path prefix for commissioning scripts.  Commissioning scripts will be
# extracted into this directory.
ARCHIVE_PREFIX = "commissioning.d"

# Name of the file where the commissioning scripts store lshw output.
LSHW_OUTPUT_NAME = '00-maas-01-lshw.out'

# Name of the file where the commissioning scripts store LLDP output.
LLDP_OUTPUT_NAME = '99-maas-02-capture-lldp.out'


def make_function_call_script(function, *args, **kwargs):
    """Compose a Python script that calls the given function.

    The function's source will be obtained by inspection. Ensure that
    the function is fully self-contained; don't rely on variables or
    imports from the module in which it is defined.

    The given arguments will be used when calling the function in the
    composed script. They are serialised into JSON with the
    limitations on types that that implies.

    :return: `bytes`
    """
    template = dedent("""\
    #!/usr/bin/python
    # -*- coding: utf-8 -*-

    from __future__ import (
        absolute_import,
        print_function,
        unicode_literals,
        )

    import json

    __metaclass__ = type
    __all__ = [{function_name!r}]

    {function_source}

    if __name__ == '__main__':
        args = json.loads({function_args!r})
        kwargs = json.loads({function_kwargs!r})
        {function_name}(*args, **kwargs)
    """)
    script = template.format(
        function_name=function.__name__.decode('ascii'),
        function_source=dedent(getsource(function).decode('utf-8')).strip(),
        function_args=json.dumps(args).decode('utf-8'),
        function_kwargs=json.dumps(kwargs).decode('utf-8'),
    )
    return script.encode("utf-8")


# Built-in script to run lshw.
LSHW_SCRIPT = dedent("""\
    #!/bin/sh
    lshw -xml
    """)


def set_hardware_details(node, raw_content):
    """Process the results of LSHW_SCRIPT."""
    node.set_hardware_details(raw_content)


# Built-in script to detect virtual instances. It will only detect QEMU
# for now and may need expanding/generalising at some point.
VIRTUALITY_SCRIPT = dedent("""\
    #!/bin/sh
    grep '^model name.*QEMU.*' /proc/cpuinfo >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "virtual"
    else
        echo "notvirtual"
    fi
    """)


def set_virtual_tag(node, raw_content):
    """Process the results of VIRTUALITY_SCRIPT."""
    tag, _ = Tag.objects.get_or_create(name='virtual')
    if 'notvirtual' in raw_content:
        node.tags.remove(tag)
    else:
        node.tags.add(tag)


# This function must be entirely self-contained. It must not use
# variables or imports from the surrounding scope.
def lldpd_install(config_file):
    """Installs and configures `lldpd` for passive capture.

    `config_file` refers to a shell script that is sourced by
    `lldpd`'s init script, i.e. it's Upstart config on Ubuntu.

    It selects the following options for the `lldpd` daemon:

    -c  Enable the support of CDP protocol to deal with Cisco routers
        that do not speak LLDP. If repeated, CDPv1 packets will be
        sent even when there is no CDP peer detected.

    -f  Enable the support of FDP protocol to deal with Foundry routers
        that do not speak LLDP. If repeated, FDP packets will be sent
        even when there is no FDP peer detected.

    -s  Enable the support of SONMP protocol to deal with Nortel
        routers and switches that do not speak LLDP. If repeated,
        SONMP packets will be sent even when there is no SONMP peer
        detected.

    -e  Enable the support of EDP protocol to deal with Extreme
        routers and switches that do not speak LLDP. If repeated, EDP
        packets will be sent even when there is no EDP peer detected.

    -r  Receive-only mode. With this switch, lldpd will not send any
        frame. It will only listen to neighbors.

    These flags are chosen so that we're able to capture information
    from a broad spectrum of equipment, but without advertising the
    node's temporary presence.

    """
    from subprocess import check_call
    check_call(("apt-get", "install", "--yes", "lldpd"))
    from codecs import open
    with open(config_file, "a", "ascii") as fd:
        fd.write('\n')  # Ensure there's a newline.
        fd.write('# Configured by MAAS:\n')
        fd.write('DAEMON_ARGS="-c -f -s -e -r"\n')
    check_call(("service", "lldpd", "restart"))


# This function must be entirely self-contained. It must not use
# variables or imports from the surrounding scope.
def lldpd_wait(reference_file, time_delay):
    """Wait until `lldpd` has been running for `time_delay` seconds.

    On an Ubuntu system, `reference_file` is typically `lldpd`'s UNIX
    socket in `/var/run`.

    """
    from os.path import getmtime
    time_ref = getmtime(reference_file)
    from time import sleep, time
    time_remaining = time_ref + time_delay - time()
    if time_remaining > 0:
        sleep(time_remaining)


# This function must be entirely self-contained. It must not use
# variables or imports from the surrounding scope.
def lldpd_capture():
    """Capture LLDP information from `lldpd` in XML form."""
    from subprocess import check_call
    check_call(("lldpctl", "-f", "xml"))


_xpath_routers = "/lldp//id[@type='mac']/text()"


def extract_router_mac_addresses(raw_content):
    """Extract the routers' MAC Addresses from raw LLDP information."""
    if not raw_content:
        return None
    assert isinstance(raw_content, bytes)
    parser = etree.XMLParser()
    doc = etree.XML(raw_content.strip(), parser)
    return doc.xpath(_xpath_routers)


def set_node_routers(node, raw_content):
    """Process recently captured raw LLDP information.

    The list of the routers' MAC Addresses is extracted from the raw LLDP
    information and stored on the given node.
    """
    routers = extract_router_mac_addresses(raw_content)
    if routers is None:
        node.routers = None
    else:
        node.routers = [MAC(router) for router in routers]
    node.save()


def null_hook(node, raw_content):
    """Intentionally do nothing.

    Use this to explicitly ignore the response from a built-in
    commissioning script.
    """


# Built-in commissioning scripts.  These go into the commissioning
# tarball together with user-provided commissioning scripts.
# To keep namespaces separated, names of the built-in scripts must be
# prefixed with "00-maas-" or "99-maas-".
#
# The dictionary is keyed on the output filename that the script
# produces. This is so it can be looked up later in the post-processing
# hook.
#
# The contents of each dictionary entry are another dictionary with
# keys:
#   "name" -> the script's name
#   "content" -> the actual script
#   "hook" -> a post-processing hook.
#
# The post-processing hook is a function that will be passed the node
# and the raw content of the script's output, e.g. "hook(node, raw_content)"
BUILTIN_COMMISSIONING_SCRIPTS = {
    LSHW_OUTPUT_NAME: {
        'content': LSHW_SCRIPT.encode('ascii'),
        'hook': set_hardware_details,
    },
    '00-maas-02-virtuality.out': {
        'content': VIRTUALITY_SCRIPT.encode('ascii'),
        'hook': set_virtual_tag,
    },
    '00-maas-03-install-lldpd.out': {
        'content': make_function_call_script(
            lldpd_install, config_file="/etc/default/lldpd"),
        'hook': null_hook,
    },
    '99-maas-01-wait-for-lldpd.out': {
        'content': make_function_call_script(
            lldpd_wait, "/var/run/lldpd.socket", time_delay=60),
        'hook': null_hook,
    },
    LLDP_OUTPUT_NAME: {
        'content': make_function_call_script(lldpd_capture),
        'hook': set_node_routers,
    },
}


def add_names_to_scripts(scripts):
    """Derive script names from the script output filename.

    Designed for working with the `BUILTIN_COMMISSIONING_SCRIPTS`
    structure.

    """
    for output_name, config in scripts.items():
        if "name" not in config:
            script_name = os.path.basename(output_name)
            script_name, _ = os.path.splitext(script_name)
            config["name"] = script_name


add_names_to_scripts(BUILTIN_COMMISSIONING_SCRIPTS)


def add_script_to_archive(tarball, name, content, mtime):
    """Add a commissioning script to an archive of commissioning scripts."""
    assert isinstance(content, bytes), "Script content must be binary."
    tarinfo = tarfile.TarInfo(name=os.path.join(ARCHIVE_PREFIX, name))
    tarinfo.size = len(content)
    # Mode 0755 means: u=rwx,go=rx
    tarinfo.mode = 0755
    # Modification time defaults to Epoch, which elicits annoying
    # warnings when decompressing.
    tarinfo.mtime = mtime
    tarball.addfile(tarinfo, BytesIO(content))


class CommissioningScriptManager(Manager):
    """Utility for the collection of `CommissioningScript`s."""

    def _iter_builtin_scripts(self):
        for script in BUILTIN_COMMISSIONING_SCRIPTS.itervalues():
            yield script['name'], script['content']

    def _iter_user_scripts(self):
        for script in self.all():
            yield script.name, script.content

    def _iter_scripts(self):
        return chain(
            self._iter_builtin_scripts(),
            self._iter_user_scripts())

    def get_archive(self):
        """Produce a tar archive of all commissioning scripts.

        Each of the scripts will be in the `ARCHIVE_PREFIX` directory.
        """
        binary = BytesIO()
        scripts = sorted(self._iter_scripts())
        with tarfile.open(mode='w', fileobj=binary) as tarball:
            add_script = partial(add_script_to_archive, tarball, mtime=now())
            for name, content in scripts:
                add_script(name, content)
        return binary.getvalue()


class CommissioningScript(Model):
    """User-provided commissioning script.

    Actually a commissioning "script" could be a binary, e.g. because a
    hardware vendor supplied an update in the form of a binary executable.
    """

    class Meta(DefaultMeta):
        """Needed for South to recognize this model."""

    objects = CommissioningScriptManager()

    name = CharField(max_length=255, null=False, editable=True, unique=True)
    content = BinaryField(null=False)
