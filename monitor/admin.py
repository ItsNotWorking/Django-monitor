
from django.contrib import admin
from django.contrib.admin.filterspecs import FilterSpec

from monitor.actions import (
    approve_selected, challenge_selected, reset_to_pending
)
from monitor.filter import MonitorFilter
from monitor import model_from_queue, get_monitor_entry
from monitor.conf import (
    PENDING_STATUS, CHALLENGED_STATUS, APPROVED_STATUS
)

# Our objective is to place the custom monitor-filter on top
FilterSpec.filter_specs.insert(
    0, (lambda f: getattr(f, 'monitor_filter', False), MonitorFilter)
)

class MonitorAdmin(admin.ModelAdmin):
    """Use this for monitored models."""

    # Which fields are to be made readonly after approval.
    protected_fields = ()

    def __init__(self, model, admin_site):
        """ Overridden to add a custom filter to list_filter """
        super(MonitorAdmin, self).__init__(model, admin_site)
        self.list_filter = [self.opts.pk.attname] + list(self.list_filter)
        self.list_display = list(self.list_display) + ['get_status_display']

    def queryset(self, request):
        """
        Django does not allow using non-fields in list_filter. (As of 1.3).
        Using params not mentioned in list_filter will raise error in changelist.
        We want to enable status based filtering (status is not a db_field).
        We will check the request.GET here and if there's a `status` in it,
        Remove that and filter the qs by status.
        """
        qs = super(MonitorAdmin, self).queryset(request)
        status = request.GET.get('status', None)
        # status is not among list_filter entries. So its presence will raise
        # IncorrectLookupParameters when django tries to build-up changelist.
        # We no longer need that param after leaving here. So let's remove it.
        if status:
            get_dict = request.GET.copy()
            del get_dict['status']
            request.GET = get_dict
        # ChangeList will use this custom queryset. So we've done it!
        if status and status == PENDING_STATUS:
            qs = qs.pending()
        elif status and status == CHALLENGED_STATUS:
            qs = qs.challenged()
        elif status and status == APPROVED_STATUS:
            qs = qs.approved()
        return qs

    def is_monitored(self):
        """Returns whether the underlying model is monitored or not."""
        return bool(model_from_queue(self.model))

    def get_readonly_fields(self, request, obj = None):
        """ Overridden to include protected_fields as well."""
        if self.is_monitored() and obj is not None and obj.status == APPROVED_STATUS:
            return self.readonly_fields + self.protected_fields
        return self.readonly_fields

    def get_actions(self, request):
        """ For monitored models, we need 3 more actions."""
        actions = super(MonitorAdmin, self).get_actions(request)
        mod_perm = '%s.moderate_%s' % (
            self.opts.app_label.lower(), self.opts.object_name.lower()
        )
        change_perm = mod_perm.replace('moderate', 'change')
        if request.user.has_perm(mod_perm):
            descr = getattr(
                approve_selected, 'short_description', 'approve selected'
            )
            actions.update({
                'approve_selected': (approve_selected, 'approve_selected', descr)
            })
            descr = getattr(
                challenge_selected, 'short_description', 'challenge selected'
            )
            actions.update({
                'challenge_selected': (challenge_selected, 'challenge_selected', descr)
            })
        if request.user.has_perm(change_perm):
            descr = getattr(
                reset_to_pending, 'short_description', 'reset to pending'
            )
            actions.update({
                'reset_to_pending': (reset_to_pending, 'reset_to_pending', descr)
            })
        return actions

    def has_moderate_permission(self, request):
        """
        Returns true if the given request has permission to moderate objects
        of the model corresponding to this model admin.
        """
        mod_perm = '%s.moderate_%s' % (
            self.opts.app_label.lower(), self.opts.object_name.lower()
        )
        return request.user.has_perm(mod_perm)

    def has_delete_permission(self, request, obj = None):
        """
        If ``can_delete_approved`` is set to False in moderation queue and
        the given object is approved, this will return False. Otherwise,
        this behaves the same way as the parent class method does.
        """
        model = model_from_queue(self.opts.model)
        if (
            model and (not model['can_delete_approved']) and
            obj is not None and get_monitor_entry(obj).is_approved()
        ):
            return False
        return super(MonitorAdmin, self).has_delete_permission(request, obj)

