from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError


class StaffUserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    scan_credits_total = forms.IntegerField(min_value=0, initial=0)
    is_active = forms.BooleanField(required=False, initial=True)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError("Username already exists.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords do not match.")
        return cleaned


class StaffUserEditForm(forms.Form):
    username = forms.CharField(max_length=150)
    is_active = forms.BooleanField(required=False)

    scan_credits_total = forms.IntegerField(min_value=0)
    scan_credits_used = forms.IntegerField(min_value=0)

    # Optional password reset
    new_password1 = forms.CharField(widget=forms.PasswordInput, required=False)
    new_password2 = forms.CharField(widget=forms.PasswordInput, required=False)

    def __init__(self, *args, user_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_obj = user_obj

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username=username)
        if self.user_obj:
            qs = qs.exclude(pk=self.user_obj.pk)
        if qs.exists():
            raise ValidationError("Username already exists.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 or p2:
            if not p1 or not p2:
                raise ValidationError("Please fill both new password fields.")
            if p1 != p2:
                raise ValidationError("New passwords do not match.")
        # credits sanity
        total = cleaned.get("scan_credits_total")
        used = cleaned.get("scan_credits_used")
        if total is not None and used is not None and used > total:
            raise ValidationError("Used credits cannot be greater than total credits.")
        return cleaned

from django import forms
from .models import Document

class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["file"]

    def clean_file(self):
        f = self.cleaned_data["file"]
        # optional: size limit (example: 10MB)
        max_mb = 10
        if f.size > max_mb * 1024 * 1024:
            raise forms.ValidationError(f"File too large. Max {max_mb}MB allowed.")
        return f

from django.forms import modelformset_factory
from .models import DocumentRow


class DocumentRowForm(forms.ModelForm):
    class Meta:
        model = DocumentRow
        fields = ["serial", "number", "first_price", "second_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # bootstrap styling
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-control form-control-sm"

        # highlight invalid fields using flags stored on instance
        inst = getattr(self, "instance", None)
        if inst:
            if inst.serial_flag != DocumentRow.Flag.OK:
                self.fields["serial"].widget.attrs["class"] += " is-invalid"
            if inst.number_flag != DocumentRow.Flag.OK:
                self.fields["number"].widget.attrs["class"] += " is-invalid"
            if inst.first_flag != DocumentRow.Flag.OK:
                self.fields["first_price"].widget.attrs["class"] += " is-invalid"
            if inst.second_flag != DocumentRow.Flag.OK:
                self.fields["second_price"].widget.attrs["class"] += " is-invalid"


DocumentRowFormSet = modelformset_factory(
    DocumentRow,
    form=DocumentRowForm,
    extra=0,
    can_delete=False,
)

class CommissionForm(forms.Form):
    commission_type = forms.ChoiceField(choices=Document.CommissionType.choices)
    commission_value = forms.FloatField(min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-control"


class WinnerForm(forms.Form):
    winner_number = forms.IntegerField(min_value=0)
    prize_amount = forms.IntegerField(min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-control form-control-sm"
