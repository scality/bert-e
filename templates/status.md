# Status #

check    | status
---------|--------
{% for item in status -%}
**{{status[item].display_name}}** | {% if status[item].pass %}:green_heart:{% else %}:broken_heart:{% endif %}
{% endfor %}

{% include 'footer.md' %}
