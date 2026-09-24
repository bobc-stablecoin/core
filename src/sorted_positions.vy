# pragma version ~=0.4.3
# pragma nonreentrancy off

"""
@title Rate-Ordered Positions
@license AGPL-3.0-or-later
@notice Doubly linked list of borrower addresses sorted by annual rate.
@dev Callers pass the neighboring nodes. Same rates keep the order the hints choose,
     which is after existing equals when hints are built by a forward walk.
"""


struct Node:
    prev: address
    next: address
    annual_rate: uint256
    exists: bool


# @dev First borrower in ascending annual-rate order.
_first: address


# @dev Last borrower in ascending annual-rate order.
_last: address


# @dev Links and rate for each inserted borrower.
_nodes: HashMap[address, Node]


@deploy
def __init__():
    """No initial nodes."""
    pass


@internal
@view
def _head() -> address:
    """Return the lowest-rate borrower, or the zero address when the list is empty."""
    return self._first


@internal
@view
def _next(account: address) -> address:
    """Return the successor of `account`, or the zero address at the tail."""
    return self._nodes[account].next


@internal
@view
def _contains(account: address) -> bool:
    """Return whether `account` is currently linked."""
    return self._nodes[account].exists


@internal
def _insert(account: address, annual_rate: uint256, prev: address, next: address):
    """Link `account` between `prev` and `next` when the hints are adjacent and ordered."""
    assert account != empty(address), "List: zero account"
    assert prev != account and next != account, "List: self hint"
    assert not self._nodes[account].exists, "List: exists"
    self._assert_hints(annual_rate, prev, next)

    self._nodes[account] = Node(
        prev=prev,
        next=next,
        annual_rate=annual_rate,
        exists=True,
    )
    if prev == empty(address):
        self._first = account
    else:
        previous: Node = self._nodes[prev]
        previous.next = account
        self._nodes[prev] = previous
    if next == empty(address):
        self._last = account
    else:
        following: Node = self._nodes[next]
        following.prev = account
        self._nodes[next] = following


@internal
def _remove(account: address):
    """Unlink `account`. Hints for a later insert must describe the list after this call."""
    node: Node = self._nodes[account]
    assert node.exists, "List: missing"
    if node.prev == empty(address):
        self._first = node.next
    else:
        previous: Node = self._nodes[node.prev]
        previous.next = node.next
        self._nodes[node.prev] = previous
    if node.next == empty(address):
        self._last = node.prev
    else:
        following: Node = self._nodes[node.next]
        following.prev = node.prev
        self._nodes[node.next] = following
    self._nodes[account] = Node(
        prev=empty(address),
        next=empty(address),
        annual_rate=0,
        exists=False,
    )


@internal
@view
def _assert_hints(annual_rate: uint256, prev: address, next: address):
    """Revert unless `prev` and `next` are adjacent and `annual_rate` belongs between them."""
    if prev == empty(address) and next == empty(address):
        assert self._first == empty(address), "List: bad hint"
        return
    if prev == empty(address):
        assert self._first == next, "List: bad hint"
        assert self._nodes[next].exists, "List: bad hint"
        assert self._nodes[next].prev == empty(address), "List: bad hint"
        assert annual_rate <= self._nodes[next].annual_rate, "List: bad hint"
        return
    if next == empty(address):
        assert self._last == prev, "List: bad hint"
        assert self._nodes[prev].exists, "List: bad hint"
        assert self._nodes[prev].next == empty(address), "List: bad hint"
        assert self._nodes[prev].annual_rate <= annual_rate, "List: bad hint"
        return
    assert self._nodes[prev].next == next, "List: bad hint"
    assert self._nodes[next].prev == prev, "List: bad hint"
    assert self._nodes[prev].annual_rate <= annual_rate, "List: bad hint"
    assert annual_rate <= self._nodes[next].annual_rate, "List: bad hint"
