from django.conf import settings
from django.contrib import admin


def group_apps():
    """Shows each app of `settings.ADMIN_APP_GROUPS` inside the group of another
    one (say Users next to Groups) on the admin's home page and sidebar, instead
    of a group of its own. Only the listing changes: the URLs stay as they are.
    An app or group that isn't installed is skipped.
    """
    site = admin.site
    get_app_list = site.get_app_list

    def app_list(request, app_label=None):
        apps = get_app_list(request, app_label)
        by_label = {app["app_label"]: app for app in apps}
        moved = []
        for label, group in settings.ADMIN_APP_GROUPS.items():
            app, target = by_label.get(label), by_label.get(group)
            if app is None or target is None or app is target:
                continue
            target["models"] = sorted(
                [*target["models"], *app["models"]], key=lambda model: model["name"]
            )
            moved.append(app)
        return [app for app in apps if app not in moved]

    site.get_app_list = app_list
