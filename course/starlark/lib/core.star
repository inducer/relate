load("relate/_core_types.star", "Timestamp")
load("relate/_builtins.star", "error")
load("relate/_generated.star", "PY_TYPE_MAP")


def from_py(type_map: dict[str, type], obj: typing.Any):
    tp = type(obj)
    if tp == "list":
        return [from_py(type_map, li) for li in obj]
    elif tp == "tuple":
        return tuple([from_py(type_map, li) for li in obj])
    elif tp == "dict":
        converted = {name: from_py(type_map, val) for name, val in obj["fields"].items()}
        if "_record_type" in obj:
            rec_constructor = type_map[obj["_record_type"]]
            return rec_constructor(**converted)
        return converted
    else:
        return obj

