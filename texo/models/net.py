# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Where a service the hub calls may live: the local network, unless an administrator opts in.

The texts of the memory go to an embedding service, a reranker, a converter: outgoing calls, declared in the
system parameters and limited to the machine, the compose network or a private address, so that nothing of a
customer leaves the organisation by a configuration slip. One rule for every module of the hub."""
import ipaddress
from urllib.parse import urlparse

LOCAL_SUFFIXES = ('.localhost', '.local', '.internal', '.lan')


def is_local_host(host):
    """A loopback, private or link-local address; a name without a domain (a compose service, the machine
    itself) or with a local one."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        host = (host or '').lower()
        return host == 'localhost' or ('.' not in host and bool(host)) or host.endswith(LOCAL_SUFFIXES)
    return address.is_loopback or address.is_private or address.is_link_local


def is_local_url(url):
    return is_local_host(urlparse(url).hostname or '')
