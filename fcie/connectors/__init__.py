"""Source connectors.

Every connector returns ``list[DiscoveredItem]`` and never raises: failures are
reported through ``ConnectorResult.errors`` so one broken feed cannot abort a run.
"""

from .base import ConnectorResult, DiscoveredItem  # noqa: F401
from .podium_site import PodiumSiteConnector  # noqa: F401
from .social import SocialDiscoveryConnector  # noqa: F401
from .rss import RSSConnector  # noqa: F401
from .web_search import WebSearchConnector  # noqa: F401
from .youtube import YouTubeConnector  # noqa: F401

__all__ = [
    "ConnectorResult",
    "DiscoveredItem",
    "PodiumSiteConnector",
    "RSSConnector",
    "WebSearchConnector",
    "YouTubeConnector",
]
