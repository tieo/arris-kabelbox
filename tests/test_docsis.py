from arris.pages.status import DocsisChannel, DocsisStatus


def chan(status: str) -> DocsisChannel:
    return DocsisChannel("0", "SC-QAM", "", "UNSUPPORTED", "", "", status)


def test_unlocked_modem_is_offline():
    st = DocsisStatus(downstream=[chan("NEIN")] * 32, upstream=[], wan_ipv4="0.0.0.0")
    assert not st.online


def test_locked_channel_without_wan_address_is_offline():
    st = DocsisStatus(downstream=[chan("JA")], upstream=[], wan_ipv4="0.0.0.0")
    assert not st.online


def test_locked_channel_with_wan_address_is_online():
    st = DocsisStatus(downstream=[chan("NEIN"), chan("Ja")], upstream=[], wan_ipv4="203.0.113.7")
    assert st.online
