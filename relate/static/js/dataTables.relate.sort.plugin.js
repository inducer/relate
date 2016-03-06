function rm_tag(s) {
    return s.replace(/(<([^>]+)>)/g, '');
}
jQuery.extend(jQuery.fn.dataTableExt.oSort, {
    "name-asc" : function (s1, s2) {
        return rm_tag(s1).localeCompare(rm_tag(s2));
    },

    "name-desc" : function (s1, s2) {
        return rm_tag(s2).localeCompare(rm_tag(s1));
    }
});