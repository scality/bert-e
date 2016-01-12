{% if status %}

check    | status
---------|--------
{% for item in status -%}
:arrow_right: **{{status[item].display_name}}** | {% if status[item].pass %}:sunny:{% else %}:exclamation:{% endif %}
{% endfor %}

{% else %}

*Status report is not available.*

{% endif %}
