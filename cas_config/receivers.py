from django.conf import settings


def cas_attribute_callback_manager(sender, user, created, attributes, ticket,
                                   service, request, **kwargs):
    """
    Upon receiving a signal from django-cas-ng that a user was successfully logged
    in over CAS, if a CAS_ATTRIBUTE_CALLBACK is defined in settings,
    call it with the data we got from this signal.

    This is a bit of a roundabout way to do it, but allows to flexibly configure it
    without touching the main RELATE code at all.
    """
    callback = getattr(settings, 'CAS_ATTRIBUTE_CALLBACK', None)
    if callback:
        import importlib
        getattr(
            importlib.import_module(callback['module']),
            callback['function']
        )(user, created, attributes, ticket, service, request)
