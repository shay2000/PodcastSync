"""Characterization tests for the RSS feed routes.

Assertions are on structure, not on a golden file: feedgen stamps a
``lastBuildDate`` that changes on every run.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def channel_of(xml: str) -> ET.Element:
    channel = ET.fromstring(xml).find("channel")
    assert channel is not None
    return channel


async def test_feed_is_served_as_rss_xml(api, seeded):
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/rss+xml"
    assert resp.headers["cache-control"] == "max-age=300"

    root = ET.fromstring(resp.text)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"


async def test_feed_declares_the_itunes_namespace(api, seeded):
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    assert f'xmlns:itunes="{ITUNES_NS}"' in resp.text

    channel = channel_of(resp.text)
    assert channel.findtext(f"{{{ITUNES_NS}}}author") == seeded.source["name"]
    assert channel.findtext(f"{{{ITUNES_NS}}}explicit") == "no"


async def test_feed_channel_metadata_comes_from_the_source(api, seeded):
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    channel = channel_of(resp.text)

    assert channel.findtext("title") == seeded.source["name"]
    assert channel.findtext("language") == "en"
    assert channel.findtext("generator") == "PodcastSync"
    # The self link uses whichever host the client reached the server on.
    self_link = channel.find("{http://www.w3.org/2005/Atom}link")
    assert self_link is not None
    assert self_link.attrib["href"] == f"http://testserver/feed/{seeded.source_id}.xml"


async def test_feed_enclosure_points_at_the_audio_route(api, seeded):
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    (item,) = channel_of(resp.text).findall("item")

    enclosure = item.find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"] == (
        f"http://testserver/audio/{seeded.source_id}/vid00000001.mp3"
    )
    assert enclosure.attrib["length"] == str(seeded.mp3.stat().st_size)
    assert enclosure.attrib["type"] == "audio/mpeg"


async def test_feed_item_carries_youtube_link_and_duration(api, seeded):
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    (item,) = channel_of(resp.text).findall("item")

    assert item.findtext("title") == "First Episode"
    assert item.findtext("description") == "Description one"
    assert item.findtext("guid") == "vid00000001"
    assert item.findtext("link") == "https://www.youtube.com/watch?v=vid00000001"
    assert item.findtext(f"{{{ITUNES_NS}}}duration") == "1800"


async def test_feed_only_lists_completed_videos(api, seeded):
    """The pending video must not appear — there is no file to enclose."""
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    items = channel_of(resp.text).findall("item")
    assert [i.findtext("guid") for i in items] == ["vid00000001"]

    # Completing the second one adds it.
    api.db.update_video_status(
        seeded.pending_id, "completed", file_path="/nonexistent.mp3", file_size=42
    )
    resp = await api.client.get(f"/feed/{seeded.source_id}.xml")
    items = channel_of(resp.text).findall("item")
    assert {i.findtext("guid") for i in items} == {"vid00000001", "vid00000002"}


async def test_feed_for_a_source_with_no_downloads_is_still_valid(api, source):
    resp = await api.client.get(f"/feed/{source['id']}.xml")
    assert resp.status_code == 200
    assert channel_of(resp.text).findall("item") == []


async def test_feed_for_unknown_source_is_404(api):
    resp = await api.client.get("/feed/999.xml")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"


async def test_list_feeds(api, seeded):
    resp = await api.client.get("/feeds")
    assert resp.status_code == 200
    (body,) = resp.json()

    assert body == {
        "id": seeded.source_id,
        "name": seeded.source["name"],
        "source_type": "channel",
        "enabled": True,
        "feed_url": f"http://testserver/feed/{seeded.source_id}.xml",
        "video_count": 2,
        "completed_count": 1,
    }
