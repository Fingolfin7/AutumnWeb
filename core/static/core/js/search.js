$(document).ready(function() {
    $("#project-search").on('keyup',function() {

        let ajax_url = $(this).attr("data-ajax_url");
        let value = $(this).val().trim();

        if (value === "") {
            return;
        }

        $.ajax({
            url: ajax_url,
            type: 'GET',
            data: {
                'search_term': value
            },
            dataType: 'json',
            success: function(data){
                let names = data.map(({name}) => name);
                $("#project-search").autocomplete({
                    appendTo: '#project-search-results',
                    source: names
                });
            }
        });
    });

    // Trigger keyup event on focus so that the autocomplete is displayed
    $("#project-search").on('focus', function() {
        $(this).trigger('keyup');
    });

});
