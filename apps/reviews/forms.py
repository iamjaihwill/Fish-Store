from django import forms

from apps.reviews.models import Review


class ReviewForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=[(n, f"{n} star{'s' if n != 1 else ''}") for n in range(5, 0, -1)],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Review
        fields = ["rating", "title", "body", "photo", "author_name", "author_email"]
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}
        labels = {
            "body": "Your review",
            "author_name": "Display name",
            "author_email": "Email",
            "photo": "Grow-out photo (optional)",
        }

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        if customer is not None:
            # Signed-in reviewers do not retype what we already know.
            del self.fields["author_email"]
            self.fields["author_name"].initial = (
                customer.user.get_full_name() or customer.user.username
            )
        else:
            self.fields["author_email"].required = True
