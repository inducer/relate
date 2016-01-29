# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.db.utils import OperationalError


def _ignore_no_such_table(f, *args):
    try:
        return f(*args)

    except OperationalError as e:
        if "no such table" in str(e):
            # django.auth actually will not create auth_* if we're starting
            # with an empty database and a custom user model.
            pass
        else:
            raise


def forwards(apps, schema_editor):
    _ignore_no_such_table(empty_table,
            apps, schema_editor,
            "auth", "User_user_permissions")
    _ignore_no_such_table(empty_table,
            apps, schema_editor,
            "auth", "User_groups")
    _ignore_no_such_table(empty_table,
            apps, schema_editor,
            "auth", "User")


def backwards(apps, schema_editor):
    populate_table(apps, schema_editor,
                   "accounts", "User",
                   "auth", "User")
    populate_table(apps, schema_editor,
                   "accounts", "User_groups",
                   "auth", "User_groups")
    populate_table(apps, schema_editor,
                   "accounts", "User_user_permissions",
                   "auth", "User_user_permissions")


def populate_table(apps, schema_editor, from_app, from_model, to_app, to_model):
    # Due to swapped out models, which means that some model classes (and/or
    # their auto-created M2M tables) do not exist or don't function correctly,
    # it is better to use SELECT / INSERT than attempting to use ORM.
    import math

    from_table_name = make_table_name(apps, from_app, from_model)
    to_table_name = make_table_name(apps, to_app, to_model)

    max_id = get_max_id(schema_editor, from_table_name)

    # Use batches to avoid loading entire table into memory
    BATCH_SIZE = 100

    # Careful with off-by-one errors where max_id is a multiple of BATCH_SIZE
    for batch_num in range(0, int(math.floor(max_id / BATCH_SIZE)) + 1):
        start = batch_num * BATCH_SIZE
        stop = start + BATCH_SIZE
        ops = schema_editor.connection.ops
        old_rows, old_cols = fetch_with_column_names(schema_editor,
                                                     "SELECT * FROM {0} WHERE id >= %s AND id < %s;".format(
                                                         ops.quote_name(from_table_name)),
                                                     [start, stop])

        # The column names in the new table aren't necessarily the same
        # as in the old table - things like 'user_id' vs 'myuser_id'.
        # We have to map them, and this seems to be good enough for our needs:
        base_from_model = from_model.split("_")[0]
        base_to_model = to_model.split("_")[0]
        map_fk_col = lambda c: "{0}_id".format(base_to_model).lower() if c == "{0}_id".format(base_from_model).lower() else c
        new_cols = list(map(map_fk_col, old_cols))

        for row in old_rows:
            values_sql = ", ".join(["%s"] * len(new_cols))
            columns_sql = ", ".join(ops.quote_name(col_name) for col_name in new_cols)
            sql = "INSERT INTO {0} ({1}) VALUES ({2});".format(ops.quote_name(to_table_name),
                                                               columns_sql,
                                                               values_sql)

            # could collect and do 'executemany', but sqlite doesn't let us
            # execute more than one statement at once it seems.
            schema_editor.execute(sql, row)
    reset_sequence(apps, schema_editor, to_app, to_model)


def empty_table(apps, schema_editor, from_app, from_model):
    from_table_name = make_table_name(apps, from_app, from_model)
    ops = schema_editor.connection.ops
    schema_editor.execute("DELETE FROM {0};".format(ops.quote_name(from_table_name)))


def make_table_name(apps, app, model):
    try:
        m = apps.get_model(app, model)
        if m._meta.db_table:
            return m._meta.db_table
    except LookupError:
        pass  # for M2M fields
    return "{0}_{1}".format(app, model).lower()


def fetch_with_column_names(schema_editor, sql, params):
    c = schema_editor.connection.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    return rows, [r[0] for r in c.description]


def get_max_id(schema_editor, table_name):
    max_id = fetch_with_column_names(schema_editor, "SELECT MAX(id) FROM {0};".format(table_name), [])[0][0][0]
    if max_id is None:
        max_id = 0
    return max_id


def reset_sequence(apps, schema_editor, app, model):
    if schema_editor.connection.vendor == 'postgresql':
        table_name = make_table_name(apps, app, model)
        sequence_name = "{0}_id_seq".format(table_name)
        schema_editor.execute("SELECT setval(%s, %s, false);", [sequence_name, get_max_id(schema_editor, table_name) + 1])



class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_custom_user_cleanup'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
