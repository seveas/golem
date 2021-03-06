Array.max = function( array ){ return Math.max.apply( Math, array ); };
function toggle_longlog() {
    $(this).parent().children('pre').toggleClass('invisible');
}
function init_clone_urls() {
    $('.urllink').each(function(index, elt) {
        $(elt).click(function() {
            $('#cloneurl').attr('value', $(this).children('span').html());
        });
    });
    $('#cloneurl').attr('value', $('.urllink').first().children('span').html());
}
function add_plain_link() {
    $('.actions').prepend('<a href="' + window.location + '?plain=1">plain</a> | ')
}

now = new Date().getTime() / 1000;
function humantime(ctime) {
    timediff = now - ctime;
    if(timediff < 0)
        return 'in the future';
    if(timediff < 60)
        return 'just now';
    if(timediff < 120)
        return 'a minute ago';
    if(timediff < 3600)
        return Math.floor(timediff / 60) + " minutes ago"
    if(timediff < 7200)
        return "an hour ago";
    if(timediff < 86400)
        return Math.floor(timediff / 3600) + " hours ago"
    if(timediff < 172800)
        return "a day ago";
    if(timediff < 2592000)
        return Math.floor(timediff / 86400) + " days ago"
    if(timediff < 5184000)
        return "a month ago";
    if(timediff < 31104000)
        return Math.floor(timediff / 2592000) + " months ago"
    if(timediff < 62208000)
        return "a year ago";
    return Math.floor(timediff / 31104000) + " years ago"
}
