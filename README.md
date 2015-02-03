# django-pgjsonb
Django Postgres JSONB Fields support with lookups

Originaly inspired by [django-postgres](https://bitbucket.org/schinckel/django-postgres/)

Install
=======

`pip install django-pgjsonb`

Use
===

```python
from django_pgjsonb import JSONField

class Article(models.Model):
	meta=JSONField([null=True,default={}])
```

Lookups
=======
###Contains wide range of lookups support natively by postgres

1. `has` :if field has specific key *`("?")`*

	```python
	Artile.objects.filter(meta__has="author")
	```

2. `has_any` : if field has any of the specific keys *`("?|")`*

	```python
	Artile.objects.filter(meta__has_any=["author","date"])
	```
3. `has_all` : if field has all of the specific keys *`("?&")`*

	```python
	Artile.objects.filter(meta__has_all=["author","date"])
	```
4. `contains` : if field contains the specific keys and values *`("@>")`*
	```python
	Article.objects.filter(meta__contains={"author":"yjmade","date":"2014-12-13"})
	```

5. `in` or `contained_by` : if all field key and value  contain by input *`("<@")`*
	```python
	Artile.objects.filter(meta__in={"author":"yjmade","date":"2014-12-13"})
	```

6. `len` : the length of the array ,transform to int,and can followed int lookup like gt or lt *`("jsonb_array_length()")`*

	```python
	Artile.objects.filter(meta__authors__len__gte=3)
	Article.objects.filter(meta__authors__len=10)
	```
7. `as_(text,int,float,bool,date,datetime)` : transform json field into sepcific data type so that you can follow operation of this type *`("CAST(FIELD as TYPE)")`*

	```python
	Article.objects.filter(meta__date__as_datetime__year__range=(2012,2015))
	Article.objects.filter(meta__view_count__as_float__gt=100)
	Article.objects.filter(meta__title__as_text__iregex=r"^\d{4}")
	```
8. `path_(PATH)` : get the specific path, path split by '_' *`("#>")`*

	```python
	Article.objects.filter(meta__path_author_articles__contains="show me the money")
	```

Add function to QuerySet
========================
1.`select_json("JSON_PATHS",field_name="JSON_PATHS")`

JSON_PATHS in format of path seperate by "__",like "meta__location__geo_info". It will use queryset's `extra` method to transform a value inside json as a field.
If no fields_name provided,it will generate a field name with lookups seperate by _ without the json field self's name,so `select_json("meta__author__name")` equal to `select_json("author_name")`

```python
Article.objects.select_json("meta__author__name",geo="meta__location__geo_info")`
```

 This operation will translate to sql as

 ```sql
 SELECT "article"."meta"->'location'->'geo_info' as "geo", "article"."meta"->'author'->'name' as "author_name"
 ```
  After select_json ,the field_name can be operate in values() and values_list() method,so that

  1. select only one sepecific value inside json
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




#####For more infomation about raw jsonb operation,please see [PostgreSQL Document](http://www.postgresql.org/docs/9.4/static/functions-json.html)
