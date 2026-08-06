# Makefile: build Final_Report.pdf from Final_Report.md using pandoc
#
# Requirements: pandoc and a LaTeX engine (xelatex recommended).

MD      := Final_Report.md
PDF     := $(MD:.md=.pdf)
ENGINE  ?= xelatex
FIGURES := $(wildcard figures/*.png figures/*.jpg figures/*.jpeg figures/*.pdf figures/*.svg)

PANDOC_FLAGS := \
	--pdf-engine=$(ENGINE) \
	--standalone \
	-V documentclass=article \
	-V fontsize=11pt \
	-V papersize=a4 \
	-V geometry:margin=2.5cm

.PHONY: all clean

all: $(PDF)

$(PDF): $(MD) $(FIGURES)
	pandoc $(PANDOC_FLAGS) $< -o $@

clean:
	rm -f $(PDF)
