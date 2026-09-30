{% if status %}

check    | status
---------|--------
{% for item in status -%}
:arrow_right: **{{status[item].display_name}}** | {% if status[item].pending %}:hourglass: {{ status[item].details | join(' — ') }}{% elif status[item].pass %}:sunny:{% if status[item].details %} {{ status[item].details | join(' — ') }}{% endif %}{% else %}:exclamation: {{ status[item].details | join(' — ') }}{% endif %}
{% endfor %}

:sunny: satisfied — :exclamation: missing — :hourglass: not yet evaluated

{% else %}

*Status report is not available.*

{% endif %}
