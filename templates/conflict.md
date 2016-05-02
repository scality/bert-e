{% extends "message.md" %}

{% block title -%}
Conflict during merge
{% endblock %}

{% block message %}
A conflict has been raised during the merge of `{{ source.name }}`
into integration branch `{{ destination.name }}`.

{% if origin %}
Since the conflict was detected between your feature branch and the original
target of your pull request, you are expected to resolve the conflict *on your
feature branch* (`{{ source.name }}`) and let your fix propagate through the
integration cascade.
{% else %}
*Please resolve the conflict on the integration branch manually.*

Here are the steps to resolve this conflict:

```
#!bash
 $ git fetch
 $ git checkout {{ destination.name }}
 $ git merge origin/{{ source.name }}
 $ # <intense conflict resolution>
 $ git push origin HEAD:{{ destination.name }}
```

After the push, please comment this pull request to resume the procedure.
{%endif%}
{% endblock %}
