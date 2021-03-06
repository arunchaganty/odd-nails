from django.db import models, transaction
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.conf import settings

from .util import CoreNLPService

# TODO(chaganty): include a from_to stanza/dict methods.

class Document(models.Model):
    """
    Represents metadata about a document.
    """
    class Meta:
        if not settings.CORENLP_USE_TABLENAME_PREFIX:
            db_table = "document"
        managed = settings.CORENLP_MANAGE_TABLES
    id = models.TextField(primary_key=True)
    corpus_id = models.TextField(default='default', help_text="Namespace of the document collection.")
    source = models.TextField(default='default', help_text="Tracks the document source.")
    timestamp = models.DateTimeField(null=True, help_text="Date of the document")
    title = models.TextField(help_text="Title for the document")
    gloss = models.TextField(help_text="The entire document")
    metadata = models.TextField(default='', blank=True, help_text="Miscellaneous metadata in json")

    def __str__(self):
        return self.gloss

    def __repr__(self):
        return "[Document {} ({})]".format(self.id, self.title)

    def annotate(self, force=False, **kwargs):
        """
        Annotate these sentences.
        :param force -- annotate sentences even if they exist. 
        """
        if Sentence.objects.filter(doc=self).exists() and not force:
            return
        with transaction.atomic():
            if Sentence.objects.filter(doc=self).exists() and force:
                # Delete existing sentence and mentions.
                Sentence.objects.filter(doc=self).delete()
                Mention.objects.filter(doc=self).delete()
            annotated_document = CoreNLPService().annotate(self.gloss, **kwargs)
            Sentence.objects.bulk_create([
                Sentence(
                    corpus_id=self.corpus_id,
                    doc=self,
                    sentence_index=s.sentence_index,
                    words=s.words,
                    lemmas=s.lemmas,
                    pos_tags=s.pos_tags,
                    ner_tags=s.ner_tags,
                    doc_char_begin=[t.character_span[0] for t in s.tokens],
                    doc_char_end=[t.character_span[1] for t in s.tokens],
                    dependencies=s.depparse,
                    gloss=s.clean_text
                    ) for s in annotated_document.sentences]) # Use clean text instead of text.
            # TODO(chaganty): Get mentions from sentence.
            Mention.objects.bulk_create([])

class Sentence(models.Model):
    """
    Represents the consitutents of each sentence, with the basic
    annotations.
    """
    class Meta:
        if not settings.CORENLP_USE_TABLENAME_PREFIX:
            db_table = "document"
        managed = settings.CORENLP_MANAGE_TABLES
    # The corpus id is replicated here for the purpose of efficiency.
    corpus_id = models.TextField(help_text="Namespace of the document collection.")
    doc = models.ForeignKey(Document, help_text="Source document")
    sentence_index = models.IntegerField(help_text="Index of sentence in document (useful to order sentences)")
    words = ArrayField(models.TextField(), help_text="Array of tokens")   # Tokens
    lemmas = ArrayField(models.TextField(), help_text="Array of lemmas")  # Tokens
    pos_tags = ArrayField(models.TextField(), help_text="Array of POS tags")     # Field
    ner_tags = ArrayField(models.TextField(), help_text="Array of NER tags")     # Field.
    doc_char_begin = ArrayField(models.IntegerField(), help_text="Array of character begin positions for each token, relative to document start")
    doc_char_end = ArrayField(models.IntegerField(), help_text="Array of character end positions for each token, relative to document start")
    # NOTE: constituencies are ignored because they are usually very expensive to compute
    dependencies = models.TextField(null=True, db_column = 'dependencies_extra', help_text="Dependency tree in CONLL format")
    # NOTE: other dependency formats like dependencies_malt are ignored.
    gloss = models.TextField(help_text="Raw text representation of the sentence")
    searchable = SearchVectorField('gloss')

    def __str__(self):
        return self.gloss

    def __repr__(self):
        return "[Sentence {}]".format(self.gloss[:50])

class Mention(models.Model):
    """
    Represents occurrences of entity mentions in the document.
    """
    class Meta:
        if not settings.CORENLP_USE_TABLENAME_PREFIX:
            db_table = "mention"
        managed = settings.CORENLP_MANAGE_TABLES

    id = models.BigIntegerField(primary_key = True)
    # The corpus id is replicated here for the purpose of efficiency.
    corpus_id = models.TextField(help_text="Namespace of the document collection.")
    doc = models.ForeignKey(Document, help_text="Source document")
    sentence = models.ForeignKey(Sentence, help_text="Sentence containing the mention")

    # provenance information
    token_begin = ArrayField(models.IntegerField(), help_text="Token offset within sentence where this entity mention starts")
    token_end = ArrayField(models.IntegerField(), help_text="Token offset within sentence where this entity mention ends")
    doc_char_begin = ArrayField(models.IntegerField(), help_text="Character offset within the document where this entity mention starts")
    doc_char_end = ArrayField(models.IntegerField(), help_text="Character offset within the document where this entity mention ends")
    doc_canonical_char_begin = ArrayField(models.IntegerField(), help_text="Character offset within the document where this entity's canonical mention (resolved through coref) starts")
    doc_canonical_char_end = ArrayField(models.IntegerField(), help_text="Character offset within the document where this entity's canonical mention (resolved through coref) ends")

    # linking information
    ner = models.CharField(max_length=64, help_text="Type of entity, usually an NER tag")
    best_entity = models.TextField(help_text="The best entity link for this mention")
    best_entity_score = models.FloatField(null=True, help_text="Linking score for the best entity match")
    unambiguous_link = models.BooleanField(help_text="Was the linking unambigiuous?")
    alt_entity = models.TextField(help_text="The 2nd best entity link for this mention")
    alt_entity_score = models.FloatField(null=True, help_text="Linking score for the 2nd best entity match")

    gloss = models.TextField(null=True, help_text="Raw text representation of the mention")

    def __str__(self):
        return self.gloss

    def __repr__(self):
        return "[Mention {}]".format(self.gloss[:50])

class Relation(models.Model):
    """
    Represents a relation between two entities in a document.
    If has_title('Obama', 'president') then:
        'Obama' is the entity
        'has_title' is the relation
        'president' is the slot value
    """
    class Meta:
        if not settings.CORENLP_USE_TABLENAME_PREFIX:
            db_table = "kbp_slot_fill"
        managed = settings.CORENLP_MANAGE_TABLES

    id = models.BigIntegerField(primary_key = True)
    # Provenance
    corpus_id = models.TextField(help_text="Namespace of the document collection.")
    sentence = models.ForeignKey(Sentence, help_text="Sentence containing the mention")

    # Entity
    entity = models.ForeignKey(Mention, null = True, related_name='entity_relations', help_text="Link to the the entity mention")
    # Replicated here for efficiency
    entity_name = models.TextField(help_text="The link of the entity")
    entity_gloss = models.TextField(help_text="The textual gloss of the entity")
    # Slot
    slot_value = models.ForeignKey(Mention, null = True, related_name='slot_relations', help_text="Link to the the slot mention")
    # Replicated here for efficiency
    slot_value_name = models.TextField(help_text="The link of the slot value")
    slot_value_gloss = models.TextField(help_text="The textual gloss of the slot filler")

    # Relation
    relation = models.TextField(help_text="Relation between the entity and slot value")
    score = models.FloatField(help_text="Score predicted by the relation extractor")

    def __str__(self):
        return "{} {} {}".format(self.entity_gloss, self.relation, self.slot_value_gloss)

    def __repr__(self):
        return "[Relation {} {} {}]".format(self.entity_gloss, self.relation, self.slot_value_gloss)

