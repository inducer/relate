# This is an example of a more complicated CAS login procedure,
# where declaring an attribute mapping is insufficient.
#
# Code in this function will execute on every CAS login and interpret
# the attributes in whichever way you see fit, for example, using them to create
# Participation or ParticipationPreapproval objects.

def cas_callback(user, created, attributes, ticket, service, request):
    print("User:", user)
    print("CAS Attributes as received:", attributes)
    print("Making the user feel at home...")

    user.first_name = attributes.get('givenName', '')
    user.last_name = attributes.get('sn', '')
    user.name_verified = attributes.get('is_name_verified', 'FALSE') == 'TRUE'
    user.is_staff = attributes.get('is_staff', 'FALSE') == 'TRUE'
    user.is_superuser = attributes.get('is_superuser', 'FALSE') == 'TRUE'
    user.is_active = attributes.get('is_active', 'FALSE') == 'TRUE'
    user.email = attributes.get('email',)
    user.institutional_id = user.username
    user.institutional_id_verified = True
    user.save()

