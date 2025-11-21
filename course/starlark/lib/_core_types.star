load("relate/_builtins.star", "parse_date_spec")

Timestamp = float

FlowSessionExpirationMode = enum("end", "roll_over")
ParticipationStatus = enum("requested", "active", "dropped", "denied")
