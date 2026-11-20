from django.db import models
from django.test import SimpleTestCase
from django.test.utils import isolate_apps

from apps.core.models import BaseModel


@isolate_apps("apps.core")
class BaseModelTest(SimpleTestCase):
    def test_public_id_and_timestamps(self):
        class Thing(BaseModel):
            name = models.CharField(max_length=10)

            class Meta:
                app_label = "core"

        public_id = Thing._meta.get_field("public_id")
        self.assertTrue(public_id.unique)
        self.assertFalse(public_id.editable)
        self.assertTrue(Thing._meta.get_field("created_at").auto_now_add)
        self.assertTrue(Thing._meta.get_field("updated_at").auto_now)
        # The primary key stays the integer `id`.
        self.assertIsInstance(Thing._meta.pk, models.BigAutoField)
        first, second = Thing(), Thing()
        self.assertEqual(first.public_id.version, 7)
        self.assertNotEqual(first.public_id, second.public_id)
