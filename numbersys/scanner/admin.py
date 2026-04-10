from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    fields = ("scan_credits_total", "scan_credits_used", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


# Replace default User admin so credits appear inside User page
admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "scan_credits_total", "scan_credits_used", "scan_credits_remaining", "updated_at")
    search_fields = ("user__username",)
    readonly_fields = ("created_at", "updated_at")

    def scan_credits_remaining(self, obj):
        return obj.scan_credits_remaining

from .models import Document,DocumentRow

class DocumentRowInline(admin.TabularInline):
    model = DocumentRow
    extra = 0

# add into your existing DocumentAdmin
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "status", "needs_review", "issues_count", "created_at")
    list_filter = ("status", "created_at", "needs_review")
    search_fields = ("owner__username", "id")
    inlines = (DocumentRowInline,)

from .models import Winner

@admin.register(Winner)
class WinnerAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "winner_number", "prize_amount", "created_at")
    search_fields = ("winner_number", "document__id", "document__owner__username")
