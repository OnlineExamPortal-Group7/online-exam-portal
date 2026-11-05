from django.dispatch import Signal

# Sent after an exam's results are published and the transaction has committed.
# Keyword arguments: exam, published_by. Notifications (#25) can connect to it.
results_published = Signal()
