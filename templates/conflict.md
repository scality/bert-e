{% extends "message.md" %}

{% block title -%}
Conflict
{% endblock %}

{% block message %}
There was a conflict during the merge of
`{{ source.name }}` into `{{ destination.name }}`.

Here are the steps to resolve this conflict:

```
#!bash\n
 $ git fetch
 $ git checkout {{ destination.name }}
 $ git merge origin/{{ source.name }}
 $ # intense conflict fixing
 $ git add <any modified file>
 $ git commit
 $ git push
```

After the push, please comment the original PR to resume the procedure.
{% endblock %}
