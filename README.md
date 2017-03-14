# django-pgjsonb
Django Postgres JSONB Fields support with lookups

Originaly inspired by [django-postgres](https://bitbucket.org/schinckel/django-postgres/)


Change Logs
===========
2017-03-14: 0.0.24
    Add support for __near lookup with postgres earthdistance plugin, Thanks to @steinliber
    
2016-06-01: 0.0.23
	Fix value from select_json not been decode from json introduce by 0.0.18

2016-03-24: 0.0.22
	Fix error #11 remove the unexpect decode float to Decimal

2016-03-19: 0.0.21
	Fix error #10

2016-03-09: 0.0.20
	Add the array length for select_json

2016-03-08: 0.0.19
	fix when add a json field with db_index=True and it's fail to generate the create index sql

2016-03-01: 0.0.18
	we want to be able to use customize decoder to load json, so get avoid the psycopg2's decode json, just return raw text then we deserilize by the field from_db_value

2016-03-01: 0.0.17
	patch the django serilizer to not return the stringifyed result

2015-07-23: 0.0.16
	Add support for ./manage.py inspectdb

2015-06-10: 0.0.15
    Add support for db_index to add GIN index

Install
=======

`pip install django-pgjsonb`


Definition
===

```python
from django_pgjsonb import JSONField

class Article(models.Model):
	meta=JSONField([null=True,default={},decode_kwargs={},encode_kwargs={},db_index=False,db_index_options={}])
```


Encoder and Decoder Options
===
by define decode_kwargs and encode_kwargs you can use your customize json dump and load behaveior, basicly these parameters will just pass to json.loads(**decode_kwargs) and json.dumps(**encode_kwargs)

here is an example for use [EJSON](https://pypi.python.org/pypi/ejson) to store native datetime object

```python
import ejson

class Article(models.Model):
	meta=JSONField(encode_kwargs={"cls":ejson.EJSONEncoder},decode_kwargs={"cls":ejson.EJSONDecoder})
```


Add Index
=====
[new add in 0.0.15]

jsonb field support gin type index to accelerator filtering. Since JSON is a data structure contains hierarchy, so the index of jsonb field will be more complicate than another single value field. More information, please reference [Postgres document 8.14.4](http://www.postgresql.org/docs/9.4/static/datatype-json.html)

```python
meta=JSONField(db_index=True)
or
meta=JSONField(db_index=True,db_index_options={"path":"authors__name","only_contains":True})
or
meta=JSONField(db_index=True,db_index_options=[{},{"path":"authors__name","only_contains":True}])
```

When set db_index as True and do not set db_index_options, it will generate default GIN index, most case it's enough.

When specify ```db_index_options={"only_contains":True}```, the index will be as the non-default GIN operator class jsonb_path_ops that supports indexing the ```contains``` operator only, but it's consume less space and more efficient.

When specify the path parameter in db_index_options, ```db_index_options={"path":"authors__name"}```, then index will generate to the specify path, so that ```Article.objects.filter(meta__authors__name__contains=["asd"])``` can utilize the index.

So you can create multiple index in one JSONField, just pass the db_index_options parameter as a list that contains multiple options, it will generate multiple correspond indexes. Empty dict stand for the default GIN index.


Lookups
=======
###Contains a wide range of lookups supported natively by postgres

1. `has` :if field has specific key *`("?")`*

 ```python
 Article.objects.filter(meta__has="author")
 ```

2. `has_any` : if field has any of the specific keys *`("?|")`*

 ```python
 Article.objects.filter(meta__has_any=["author","date"])
 ```
3. `has_all` : if field has all of the specific keys *`("?&")`*

 ```python
 Article.objects.filter(meta__has_all=["author","date"])
 ```
4. `contains` : if field contains the specific keys and values *`("@>")`*
 ```python
 Article.objects.filter(meta__contains={"author":"yjmade","date":"2014-12-13"})
 ```

5. `in` or `contained_by` : if all field key and value  contain by input *`("<@")`*
 ```python
 Article.objects.filter(meta__in={"author":"yjmade","date":"2014-12-13"})
 ```

6. `len` : the length of the array, transform to int, and can followed int lookup like gt or lt *`("jsonb_array_length()")`*

 ```python
 Article.objects.filter(meta__authors__len__gte=3)
 Article.objects.filter(meta__authors__len=10)
 ```
7. `as_(text,int,float,bool,date,datetime)` : transform json field into specific data type so that you can follow operation of this type *`("CAST(FIELD as TYPE)")`*

 ```python
 Article.objects.filter(meta__date__as_datetime__year__range=(2012,2015))
 Article.objects.filter(meta__view_count__as_float__gt=100)
 Article.objects.filter(meta__title__as_text__iregex=r"^\d{4}")
 ```
8. `path_(PATH)` : get the specific path, path split by '_' *`("#>")`*

 ```python
 Article.objects.filter(meta__path_author_articles__contains="show me the money")
 ```


Added function to QuerySet
========================
1.`select_json("JSON_PATHS",field_name="JSON_PATHS")`

JSON_PATHS in the format of paths separated by "__",like "meta__location__geo_info". It will use the queryset's `extra` method to transform a value inside json as a field.
If no field_name provided, it will generate a field name with lookups separate by _ without the json field self's name, so `select_json("meta__author__name")` is equal to `select_json(author_name="meta__author__name")`

```python
Article.objects.select_json("meta__author__name",geo="meta__location__geo_info")`
```

 This operation will translate to sql as

 ```sql
 SELECT "article"."meta"->'location'->'geo_info' as "geo", "article"."meta"->'author'->'name' as "author_name"
 ```

[new add in 0.0.20]
You can also select the length of a json array as a field by use Length object

```python
from django.pgjsonb.fields import Length
Article.objects.select_json(authors_len=Length("meta__authors")).values("authors_len")
```

  After select_json, the field_name can be operate in values() and values_list() method, so that

  1. select only one specific value inside json
  2. to group by one value inside json

is possible.

Demo:

```python
Article.objects.all().select_json(tags="meta__tags").values_list("tags")
# select only "meta"->'tags'

Article.objects.all().select_json(author_name="meta__author__name")\
	.values("author_name").annotate(count=models.Count("author_name"))
# GROUP BY "meta"->'author'->'name'
```




support geo search in jsonb
===========================

**require**: postgresql plugin: 

1. cube

2. earthdistance

3. to install these two plugin, run command below in psql

   ```
   CREATE EXTENSION cube;  
   CREATE EXTENSION earthdistance; 
   ```

how to save location  json record

```Json
{"location": [30.2, 199.4]}  # just keep a latitude, longitude list
```

Demo

```python
Article.objects.filter(data__location__near=[39.9, 116.4,5000]) # latitude，longitude，search range
```

or 

```python
Article.objects.filter(data__location__near='39.9,116.4,5000') # latitude，longitude, search range
```

**Alert**: if you don't pass exact number of params, this filter will not be used

**for more earthdistance**, see [Postgresql Earthdistance Documentation](https://www.postgresql.org/docs/8.3/static/earthdistance.html)

------------------------------------------------------------------------------------------------------------------


#####For more information about raw jsonb operation, please see [PostgreSQL Documentation](http://www.postgresql.org/docs/9.4/static/functions-json.html)