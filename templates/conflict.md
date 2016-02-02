{% extends "message.md" %}

{% block title -%}
Conflict during merge
{% endblock %}

{% block message %}
A conflict has been raised during the merge of `{{ source.name }}`
into integration branch `{{ destination.name }}`. You must
resolve the conflict on the integration branch manually.

Here are the steps to resolve this conflict:

```
#!bash
 $ git fetch
 $ git checkout {{ destination.name }}
 $ git merge origin/{{ source.name }}
 $ # <intense conflict resolution>
 $ git push
```

After the push, please comment here to resume the procedure.
{% endblock %}
