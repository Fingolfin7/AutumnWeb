$(document).ready(function() {
    let search = $('#project-search');

    search.on('keyup',function() {

        let ajax_url = $(this).attr("data-ajax_url");
        let value = $(this).val().trim();

        if (value === "") {
            return;
        }

        $.ajax({
            url: ajax_url,
            type: 'GET',
            data: {
                'search_term': value,
                //'status': 'active'
            },
            dataType: 'json',
            success: function(data){
                let names = data.map(({name}) => name);
                $("#project-search").autocomplete({
                    appendTo: '#project-search-results',
                    source: names,
                    select: function(event, ui) {
                        // Set the selected value in the hidden input
                        let selected = ui.item.value;
                        $('#parent_project').val(selected);
                    }
                });
            }
        });
    });

    // Trigger keyup event on focus so that the autocomplete is displayed
    search.on('focus', function() {
        $(this).trigger('keyup');
    });
});