frappe.listview_settings['Social Post'] = {
    add_fields: ['status'],

    get_indicator: function (doc) {
        if (doc.status === 'Draft') {
            return [__("Draft"), "grey", "status,=,Draft"];
        } else if (doc.status === 'Scheduled') {
            return [__("Scheduled"), "blue", "status,=,Scheduled"];
        } else if (doc.status === 'Publishing') {
            return [__("Publishing"), "royalblue", "status,=,Publishing"];
        } else if (doc.status === 'Published') {
            return [__("Published"), "green", "status,=,Published"];
        } else if (doc.status === 'Failed') {
            return [__("Failed"), "orange", "status,=,Failed"];
        } else if (doc.status === 'Cancelled') {
            return [__("Cancelled"), "red", "status,=,Cancelled"];
        }
    },

    // Optional: Customize primary action button and empty state
    onload: function (listview) {
        // Change "+ New" to "+ Schedule Post"
        listview.page.clear_primary_action();
        listview.page.set_primary_action(
            __('Schedule Post'),
            () => frappe.new_doc('Social Post'),
            'add'
        );

        // Custom empty state message
        setTimeout(() => {
            if (!listview.data || listview.data.length === 0) {
                const $empty = listview.$page.find('.no-result');
                if ($empty.length) {
                    $empty.find('p').first().text(__("You haven't scheduled any posts yet."));
                    $empty.find('.btn-new-doc').text(__("Schedule your first Post"));
                }
            }
        }, 100);
    },

    refresh: function (listview) {
        // Re-apply primary action after refresh
        listview.page.clear_primary_action();
        listview.page.set_primary_action(
            __('Schedule Post'),
            () => frappe.new_doc('Social Post'),
            'add'
        );
    }
};