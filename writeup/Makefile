SHELL := /bin/bash

LATEXMK := latexmk -xelatex -interaction=nonstopmode -shell-escape -outdir=out
MAIN := main
SUBMISSION := main-submission

.PHONY: all identified submission wordcount clean

all: identified submission

identified:
	$(LATEXMK) $(MAIN).tex

submission: $(SUBMISSION).tex
	$(LATEXMK) $(SUBMISSION).tex

$(SUBMISSION).tex: $(MAIN).tex
	sed -e 's/^%[[:space:]]*\(\\submissiontrue\)/\1/' $< > $@

wordcount:
	texcount -merge -sum -q \
	  1_introduction.tex 2_background.tex 3_related_work.tex \
	  4_implementation.tex \
	  5_evaluation.tex 6_conclusions.tex

clean:
	latexmk -C -outdir=out $(MAIN).tex
	latexmk -C -outdir=out $(SUBMISSION).tex
	rm -f $(SUBMISSION).tex
