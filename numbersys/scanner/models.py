from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    scan_credits_total = models.PositiveIntegerField(default=0)
    scan_credits_used = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def scan_credits_remaining(self) -> int:
        remaining = int(self.scan_credits_total) - int(self.scan_credits_used)
        return max(remaining, 0)

    def __str__(self) -> str:
        return f"Profile({self.user.username})"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_profile(sender, instance, created, **kwargs):
    # Auto-create profile when user is created in admin
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # Ensure profile exists even if older users exist
        UserProfile.objects.get_or_create(user=instance)

# Document model
from django.core.validators import FileExtensionValidator

class Document(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        PROCESSING = "PROCESSING", "Processing"
        EXTRACTED = "EXTRACTED", "Extracted"
        VERIFIED = "VERIFIED", "Verified"
        FINALIZED = "FINALIZED", "Finalized"
        FAILED = "FAILED", "Failed"
    class CommissionType(models.TextChoices):
        PERCENT = "PERCENT", "Percent (%)"
        FIXED = "FIXED", "Fixed amount"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")

    file = models.FileField(
        upload_to="documents/%Y/%m/%d/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"])],
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # later use:
    textract_job_id = models.CharField(max_length=128, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    needs_review = models.BooleanField(default=False)
    issues_count = models.PositiveIntegerField(default=0)

    # ---- calculations snapshot ----
    total_first = models.PositiveIntegerField(default=0)     # sum(F)
    total_second = models.PositiveIntegerField(default=0)    # sum(S)
    grand_total = models.PositiveIntegerField(default=0)     # total_first + total_second
    commission_type = models.CharField(max_length=10, choices=CommissionType.choices, default=CommissionType.PERCENT)
    commission_value = models.FloatField(default=0.0)        # % or fixed amount
    commission_amount = models.FloatField(default=0.0)       # calculated
    total_after_commission = models.PositiveIntegerField(default=0)
    total_prize = models.PositiveIntegerField(default=0)
    net_bill = models.IntegerField(default=0)  # can go negative if prize > total


    def __str__(self):
        return f"Doc#{self.id} {self.owner.username} [{self.status}]"
    
# DocumentRow model    
class DocumentRow(models.Model):
    class Side(models.TextChoices):
        LEFT = "LEFT", "Left"
        RIGHT = "RIGHT", "Right"

    class Flag(models.TextChoices):
        OK = "OK", "OK"
        INVALID = "INVALID", "Invalid"
        MISSING = "MISSING", "Missing"
        LOW = "LOW", "LowConfidence"   # will be used later with Textract

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="rows")
    side = models.CharField(max_length=10, choices=Side.choices)
    row_index = models.PositiveIntegerField()  # 1..30

    # left side serial (right side can keep it blank)
    serial = models.PositiveIntegerField(null=True, blank=True)

    # N, F, S (second price)
    number = models.BigIntegerField(null=True, blank=True)
    first_price = models.PositiveIntegerField(null=True, blank=True)
    second_price = models.PositiveIntegerField(null=True, blank=True)

    # flags per field (highlighting)
    serial_flag = models.CharField(max_length=12, choices=Flag.choices, default=Flag.OK)
    number_flag = models.CharField(max_length=12, choices=Flag.choices, default=Flag.OK)
    first_flag = models.CharField(max_length=12, choices=Flag.choices, default=Flag.OK)
    second_flag = models.CharField(max_length=12, choices=Flag.choices, default=Flag.OK)

    # later from Textract
    conf_number = models.FloatField(null=True, blank=True)
    conf_first = models.FloatField(null=True, blank=True)
    conf_second = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("document", "side", "row_index")
        ordering = ("side", "row_index")

    def __str__(self):
        return f"Row({self.document_id}, {self.side}, {self.row_index})"

# Winner model
class Winner(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="winners")
    winner_number = models.BigIntegerField()
    prize_amount = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Winner({self.winner_number}) prize={self.prize_amount} doc={self.document_id}"
