from __future__ import unicode_literals

import json
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.db.utils import ProgrammingError, InternalError
from django.db import models
from django.db.models.lookups import BuiltinLookup, Transform
from django.db.backends.postgresql_psycopg2.schema import DatabaseSchemaEditor
from django.db.backends.postgresql_psycopg2.introspection import DatabaseIntrospection
from django.utils import six
from psycopg2.extras import register_default_jsonb, Json
# we want to be able to use customize decoder to load json, so get avoid the psycopg2's decode json, just return raw text then we deserilize by the field from_db_value
logger = logging.getLogger(__name__)
register_default_jsonb(loads=lambda x: x)

DatabaseIntrospection.data_types_reverse[3802] = "django_pgjsonb.JSONField"


class JsonAdapter(Json):
    """
    Customized psycopg2.extras.Json to allow for a custom encoder.
    """

    def __init__(self, adapted, dumps=None, encode_kwargs=None):
        self.encode_kwargs = encode_kwargs
        super(JsonAdapter, self).__init__(adapted, dumps=dumps)

    def dumps(self, obj):
        # options = {'cls': self.encoder} if self.encoder else {}
        return json.dumps(obj, **self.encode_kwargs)


class JSONField(models.Field):
    description = 'JSON Field'

    def __init__(self, *args, **kwargs):
        self.decode_kwargs = kwargs.pop('decode_kwargs', {
            # 'parse_float': decimal.Decimal
        })
        self.encode_kwargs = kwargs.pop('encode_kwargs', {
            'cls': DjangoJSONEncoder,
        })
        db_index = kwargs.get("db_index")
        db_index_options = kwargs.pop("db_index_options", {})
        if db_index:
            self.db_index_options = db_index_options if isinstance(db_index_options, (list, tuple)) else [db_index_options]

            kwargs["db_index"] = False  # to supress the system default create_index_sql
        super(JSONField, self).__init__(*args, **kwargs)

    def get_internal_type(self):
        return 'JSONField'

    def db_type(self, connection):
        return 'jsonb'

    def get_prep_value(self, value):
        if value is None:
            return None
        return JsonAdapter(value, encode_kwargs=self.encode_kwargs)

    def get_prep_lookup(self, lookup_type, value, prepared=False):
        if lookup_type == 'has':
            # Need to ensure we have a string, as no other
            # values is appropriate.
            if not isinstance(value, six.string_types):
                value = '%s' % value
        if lookup_type in ['has_all', 'has_any']:
            # This lookup type needs a list of strings.
            if isinstance(value, six.string_types):
                value = [value]
            # This will cast numbers to strings, but also grab the keys
            # from a dict.
            value = ['%s' % v for v in value]
        if lookup_type == 'near':
            # geo type must have 3 item, longitude, latitude and search
            # range, allowed_format 'lat,lng,rang' or [lat, lng, rang]
            if isinstance(value, six.string_types):
                value = value.split(',')
            # if parmas not verify, just don't use this filter, 12756000
            # is the farest long in earth
            if len(value) != 3:
                value = [0, 0, 12756000]
        return value

    def get_db_prep_lookup(self, lookup_type, value, connection, prepared=False):
        if lookup_type in ['contains', 'in']:
            value = self.get_prep_value(value)
            return [value]

        return super(JSONField, self).get_db_prep_lookup(lookup_type, value, connection, prepared)

    def deconstruct(self):
        name, path, args, kwargs = super(JSONField, self).deconstruct()
        path = 'django_pgjsonb.fields.JSONField'
        kwargs.update(
            decode_kwargs=self.decode_kwargs,
            encode_kwargs=self.encode_kwargs
        )
        if hasattr(self, "db_index_options"):
            if self.db_index_options:
                kwargs["db_index_options"] = self.db_index_options
            kwargs["db_index"] = True
        return name, path, args, kwargs

    def to_python(self, value):
        if value is None and not self.null and self.blank:
            return ''
        # Rely on psycopg2 to give us the value already converted.
        return value

    def from_db_value(self, value, expression, connection, context):
        if value is not None:
            value = json.loads(value, **self.decode_kwargs)
        return value

    def get_transform(self, name):
        transform = super(JSONField, self).get_transform(name)
        if transform:
            return transform

        if name.startswith('path_'):
            path = '{%s}' % ','.join(name.replace('path_', '').split('_'))
            return PathTransformFactory(path)

        try:
            name = int(name)
        except ValueError:
            pass

        return GetTransform(name)


def patch_index_create():
    DatabaseSchemaEditor.create_jsonb_index_sql = "CREATE INDEX %(name)s ON %(table)s USING GIN ({path}{ops_cls})%(extra)s"

    def get_jsonb_index_name(editor, model, field, index_info):
        return editor._create_index_name(model, [field.name], suffix=editor._digest(index_info.get("path") or ""))

    def create_jsonb_index_sql(editor, model, field):
        options = field.db_index_options

        json_path_op = "->"
        sqls = {}
        for option in options:
            paths = option.get("path", "")
            if not paths:
                path = "%(columns)s"
            else:
                path_elements = paths.split("__")
                path = "(%(columns)s{}{})".format(json_path_op, json_path_op.join(["'%s'" % element for element in path_elements]))

            ops_cls = " jsonb_path_ops" if option.get("only_contains") else ""
            sql = editor.create_jsonb_index_sql.format(path=path, ops_cls=ops_cls)
            sqls[get_jsonb_index_name(editor, model, field, option)] = editor._create_index_sql(model, [field], sql=sql, suffix=(editor._digest(paths) if paths else ""))
        return sqls

    DatabaseSchemaEditor._create_jsonb_index_sql = create_jsonb_index_sql

    orig_model_indexes_sql = DatabaseSchemaEditor._model_indexes_sql
    orig_alter_field = DatabaseSchemaEditor._alter_field
    orig_add_field = DatabaseSchemaEditor.add_field

    def _model_indexes_sql(editor, model):
        output = orig_model_indexes_sql(editor, model)
        json_fields = [field for field in model._meta.local_fields if isinstance(field, JSONField) and hasattr(field, "db_index_options")]
        for json_field in json_fields:
            output.extend(editor._create_jsonb_index_sql(model, json_field).values())
        return output

    def _alter_field(editor, model, old_field, new_field, old_type, new_type,
                     old_db_params, new_db_params, strict=False):
        res = orig_alter_field(editor, model, old_field, new_field, old_type, new_type,
                               old_db_params, new_db_params, strict=False)
        if not isinstance(new_field, JSONField):
            return res
        old_index = getattr(old_field, "db_index_options", None)
        new_index = getattr(new_field, "db_index_options", None)
        if new_index != old_index:
            all_old_index_names = {get_jsonb_index_name(editor, model, new_field, index_info) for index_info in old_index} if old_index else set()
            all_new_indexe_names = {get_jsonb_index_name(editor, model, new_field, index_info) for index_info in new_index} if new_index else set()

            to_create_indexs, to_delete_indexes = (all_new_indexe_names - all_old_index_names), (all_old_index_names - all_new_indexe_names)
            if to_create_indexs:
                for index_name, sql in six.iteritems(editor._create_jsonb_index_sql(model, new_field)):
                    if index_name in to_create_indexs:
                        editor.execute(sql)

            for index_name in to_delete_indexes:
                try:
                    editor.execute(editor._delete_constraint_sql(editor.sql_delete_index, model, index_name))
                except (ProgrammingError, InternalError) as exc:
                    logger.warning(exc)
                    continue
        return res

    def add_field(editor, model, field):
        res = orig_add_field(editor, model, field)
        if not isinstance(field, JSONField):
            return res
        if getattr(field, "db_index_options", None):
            editor.deferred_sql.extend(editor._create_jsonb_index_sql(model, field).values())
        return res

    DatabaseSchemaEditor._model_indexes_sql = _model_indexes_sql
    DatabaseSchemaEditor._alter_field = _alter_field
    DatabaseSchemaEditor.add_field = add_field


patch_index_create()


class PostgresLookup(BuiltinLookup):

    def process_lhs(self, qn, connection, lhs=None):
        lhs = lhs or self.lhs
        return qn.compile(lhs)

    def get_rhs_op(self, connection, rhs):
        return '%s %s' % (self.operator, rhs)


class EarthNearLookup(BuiltinLookup):
    '''
    Eeed plugin: cube and earthdistance, This class help build geo
    search sql by earthdistance func
    '''

    def process_lhs(self, qn, connection, lhs=None):
        lhs = lhs or self.lhs
        lhs_value, params = qn.compile(lhs)
        earth_lhs_value = 'll_to_earth((({0})::json->>0)::float,' \
                          '(({0})::json->>1)::float)'.format(lhs_value)
        return earth_lhs_value, params

    def get_rhs_op(self, connection, rhs):
        return '{0} earth_box(ll_to_earth({1},{1}), {1})'.format(self.operator, rhs)

    def as_sql(self, compiler, connection):
        lhs_sql, params = self.process_lhs(compiler, connection)
        rhs_sql, rhs_params = self.process_rhs(compiler, connection)
        rhs_params = [item for sublist in rhs_params
                      for item in sublist]
        params.extend(rhs_params)
        rhs_sql = self.get_rhs_op(connection, rhs_sql)
        return '%s %s' % (lhs_sql, rhs_sql), params


class Near(EarthNearLookup):
    lookup_name = 'near'
    operator = '<@'


JSONField.register_lookup(Near)


class Has(PostgresLookup):
    lookup_name = 'has'
    operator = '?'
    prepare_rhs = False


JSONField.register_lookup(Has)


class Contains(PostgresLookup):
    lookup_name = 'contains'
    operator = '@>'


JSONField.register_lookup(Contains)


class ContainedBy(PostgresLookup):
    lookup_name = 'contained_by'
    operator = '<@'

    def as_sql(self, compiler, connection):
        lhs_sql, params = self.process_lhs(compiler, connection)
        rhs_sql, rhs_params = self.process_rhs(compiler, connection)
        params.extend(rhs_params)
        rhs_sql = self.get_rhs_op(connection, rhs_sql)
        return "%s!='{}' and %s %s" % (lhs_sql, lhs_sql, rhs_sql), params


JSONField.register_lookup(ContainedBy)


class In(ContainedBy):
    lookup_name = 'in'


JSONField.register_lookup(In)


class HasAll(PostgresLookup):
    lookup_name = 'has_all'
    operator = '?&'
    prepare_rhs = False


JSONField.register_lookup(HasAll)


class HasAny(PostgresLookup):
    lookup_name = 'has_any'
    operator = '?|'
    prepare_rhs = False


JSONField.register_lookup(HasAny)


# class ArrayLength(BuiltinLookup):
#     lookup_name = 'array_length'

#     def as_sql(self, qn, connection):
#         lhs, lhs_params = self.process_lhs(qn, connection)
#         rhs, rhs_params = self.process_rhs(qn, connection)
#         params = lhs_params + rhs_params
#         return 'jsonb_array_length(%s) = %s' % (lhs, rhs), params

# JSONField.register_lookup(ArrayLength)

class ArrayLenTransform(Transform):
    lookup_name = 'len'

    @property
    def output_field(self):
        return models.IntegerField()

    def as_sql(self, qn, connection):
        lhs, params = qn.compile(self.lhs)
        return 'jsonb_array_length(%s)' % lhs, params


JSONField.register_lookup(ArrayLenTransform)


class TransformMeta(type(Transform)):

    def __init__(cls, *args):  # noqa
        super(TransformMeta, cls).__init__(*args)
        cls.lookup_name = "as_%s" % (cls.lookup_type or cls.type)

        if cls.__name__ != "AsTransform":
            JSONField.register_lookup(cls)


class AsTransform(six.with_metaclass(TransformMeta, Transform)):
    type = None
    lookup_type = None
    field_type = None

    def as_sql(self, qn, connection):
        lhs, params = qn.compile(self.lhs)
        if "->" in lhs:
            last = params
        elif "#>" in lhs:
            lhs = lhs.replace('#> %s)', '')
            attrs = params[0]
            i = 0
            while i < len(attrs) - 1:
                attr = "-> '" + attrs[i] + "'"
                lhs += attr
                i += 1
            lhs += ' -> %s)'

            last = [attrs[-1]]

        splited = lhs.rsplit("->", 1)
        lhs = "->>".join(["->".join(splited[:-1]), splited[-1]])
        return "CAST(%s as %s)" % (lhs, self.type), last

    @property
    def output_field(self):
        return self.field_type()


class JsonAsText(AsTransform):
    type = "text"
    field_type = models.CharField


class JsonAsInteger(AsTransform):
    type = "integer"
    field_type = models.IntegerField
    lookup_type = "int"


class JsonAsFloat(AsTransform):
    type = "float"
    field_type = models.FloatField


class JsonAsBool(AsTransform):
    type = "boolean"
    field_type = models.NullBooleanField
    lookup_type = "bool"


class JsonAsDate(AsTransform):
    type = "date"
    field_type = models.DateField


class JsonAsDatetime(AsTransform):
    lookup_type = "datetime"
    field_type = models.DateTimeField

    @property
    def type(self):
        from django.conf import settings
        if settings.USE_TZ:
            return "timestamptz"
        else:
            return "timestamp"


class Get(Transform):

    def __init__(self, name, *args, **kwargs):
        super(Get, self).__init__(*args, **kwargs)
        self.name = name

    def as_sql(self, qn, connection):
        lhs, params = qn.compile(self.lhs)
        # So we can run a query of this type against a column that contains
        # both array-based and object-based (and possibly scalar) values,
        # we need to add an additional WHERE clause that ensures we only
        # get json objects/arrays, as per the input type.
        # It would be really nice to be able to see if these clauses
        # have already been applied.

        # if isinstance(self.name, six.string_types):
        # Also filter on objects.
        #     filter_to = "%s @> '{}' AND" % lhs
        #     self.name = "'%s'" % self.name
        # elif isinstance(self.name, int):
        # Also filter on arrays.
        #     filter_to = "%s @> '[]' AND" % lhs
        if isinstance(self.name, int):
            return '%s -> %s' % (lhs, self.name), params
        return '%s -> \'%s\'' % (lhs, self.name), params


class GetTransform(object):

    def __init__(self, name):
        self.name = name

    def __call__(self, *args, **kwargs):
        return Get(self.name, *args, **kwargs)


class Path(Transform):

    def __init__(self, path, *args, **kwargs):
        super(Path, self).__init__(*args, **kwargs)
        self.path = path

    def as_sql(self, qn, connection):
        lhs, params = qn.compile(self.lhs)
        # Because path operations only work on non-scalar types, we
        # need to filter out scalar types as part of the query.
        return "({0} @> '[]' OR {0} @> '{{}}') AND {0} #> '{1}'".format(lhs, self.path), params


class PathTransformFactory(object):

    def __init__(self, path):
        self.path = path

    def __call__(self, *args, **kwargs):
        return Path(self.path, *args, **kwargs)


def patch_select_json():
    class SQLStr(six.text_type):
        output_field = JSONField()

    def select_json(query, *args, **kwargs):
        if not args and not kwargs:
            return query

        def get_sql_str(model, opr):
            if isinstance(opr, six.string_types):
                opr_elements = opr.split("__")
                field = opr_elements.pop(0)
                select_elements = ['"%s"."%s"' % (model._meta.db_table, field)] + [("%s" if name.isnumeric() else "'%s'") % name for name in opr_elements]
                return "_".join(opr_elements), SQLStr(" -> ".join(select_elements))
            elif isinstance(opr, Length):
                annotate_name, sql = get_sql_str(model, opr.field_select)
                return annotate_name + "_len", SQLStr("jsonb_array_length(%s)" % sql)

        return query.extra(select=dict(
            [get_sql_str(query.model, opr) for opr in args],
            **{k: get_sql_str(query.model, v)[1] for k, v in six.iteritems(kwargs)}
        ))

    models.QuerySet.select_json = select_json

    orig_init = models.expressions.RawSQL.__init__

    def init(self, sql, params, output_field=None):
        if hasattr(sql, "output_field"):
            output_field = sql.output_field
        return orig_init(self, sql, params, output_field=output_field)

    models.expressions.RawSQL.__init__ = init


patch_select_json()


class Length(object):

    def __init__(self, field_select):
        self.field_select = field_select


def manager_select_json(manager, *args, **kwargs):
    return manager.all().select_json(*args, **kwargs)


models.manager.BaseManager.select_json = manager_select_json


def patch_serializer():
    from django.core.serializers.python import Serializer
    old_handle_field = Serializer.handle_field

    def handle_field(serializer, obj, field):
        if isinstance(field, JSONField):
            value = field.value_from_object(obj)
            serializer._current[field.name] = value
        else:
            return old_handle_field(serializer, obj, field)

    Serializer.handle_field = handle_field


patch_serializer()
