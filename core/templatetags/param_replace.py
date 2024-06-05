from django import template

register = template.Library()

# fix for the pagination and search queryset issue where the search query is lost when paginating.
# reference: https://medium.com/@j.yanming/simple-search-page-with-pagination-in-django-154ad259f4d7


@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs):
    """
    The param_replace function gets the current URL context from the request object in the context dictionary. It then
    gets the keyword arguments passed to it and combines them with the current URL parameters using the copy() method.
    Finally, it returns a URL-encoded string of the updated parameters.
    """
    d = context['request'].GET.copy()
    for k, v in kwargs.items():
        d[k] = v
    for k in [k for k, v in d.items() if not v]:
        del d[k]
    return d.urlencode()

