"""Views package for the Dashboard."""

from dashboard.kde.views.client_view import create_client_view
from dashboard.kde.views.server_view import create_server_view

__all__ = ["create_server_view", "create_client_view"]
